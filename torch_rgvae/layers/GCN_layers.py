import torch
from utils.utils import block_diag, stack_matrices, sum_sparse, generate_inverses, generate_self_loops
from torch.nn.modules.module import Module
from torch.nn.parameter import Parameter
from torch import nn
import math


class RelationalGraphConvolutionRP(Module):
    """
    Relational Graph Convolution (RGC) Layer for Relation Prediction
    (as described in https://arxiv.org/abs/1703.06103)
    """

    def __init__(self,
                 num_nodes=None,
                 num_relations=None,
                 in_features=None,
                 out_features=None,
                 edge_dropout=None,
                 edge_dropout_self_loop=None,
                 bias=True,
                 decomposition=None,
                 vertical_stacking=False,
                 reset_mode='xavier'):
        super(RelationalGraphConvolutionRP, self).__init__()

        assert (num_nodes is not None or num_relations is not None or out_features is not None), \
            "The following must be specified: number of nodes, number of relations and output dimension!"

        # If featureless, use number of nodes instead as input dimension
        in_dim = in_features if in_features is not None else num_nodes
        out_dim = out_features

        # Unpack arguments
        weight_decomp = decomposition['type'] if decomposition is not None and 'type' in decomposition else None
        num_bases = decomposition['num_bases'] if decomposition is not None and 'num_bases' in decomposition else None
        num_blocks = decomposition[
            'num_blocks'] if decomposition is not None and 'num_blocks' in decomposition else None

        self.num_nodes = num_nodes
        self.num_relations = num_relations
        self.in_features = in_features
        self.out_features = out_features
        self.weight_decomp = weight_decomp
        self.num_bases = num_bases
        self.num_blocks = num_blocks
        self.vertical_stacking = vertical_stacking
        self.edge_dropout = edge_dropout
        self.edge_dropout_self_loop = edge_dropout_self_loop

        # Instantiate weights
        if self.weight_decomp is None:
            self.weights = Parameter(torch.FloatTensor(num_relations, in_dim, out_dim))
        elif self.weight_decomp == 'basis':
            # Weight Regularisation through Basis Decomposition
            assert num_bases > 0, \
                'Number of bases should be set to higher than zero for basis decomposition!'
            self.bases = Parameter(torch.FloatTensor(num_bases, in_dim, out_dim))
            self.comps = Parameter(torch.FloatTensor(num_relations, num_bases))
        elif self.weight_decomp == 'block':
            # Weight Regularisation through Block Diagonal Decomposition
            assert self.num_blocks > 0, \
                'Number of blocks should be set to a value higher than zero for block diagonal decomposition!'
            assert in_dim % self.num_blocks == 0 and out_dim % self.num_blocks == 0, \
                f'For block diagonal decomposition, input dimensions ({in_dim}, {out_dim}) must be divisible ' \
                f'by number of blocks ({self.num_blocks})'
            self.blocks = nn.Parameter(
                torch.FloatTensor(num_relations, self.num_blocks, in_dim // self.num_blocks,
                                  out_dim // self.num_blocks))
        else:
            raise NotImplementedError(f'{self.weight_decomp} decomposition has not been implemented')

        # Instantiate biases
        if bias:
            self.bias = Parameter(torch.FloatTensor(out_features))
        else:
            self.register_parameter('bias', None)

        self.reset_parameters(reset_mode)

    def reset_parameters(self, reset_mode='xavier'):
        """ Initialise biases and weights (xavier or uniform) """

        if reset_mode == 'xavier':
            if self.weight_decomp == 'block':
                nn.init.xavier_uniform_(self.blocks, gain=nn.init.calculate_gain('relu'))
            elif self.weight_decomp == 'basis':
                nn.init.xavier_uniform_(self.bases, gain=nn.init.calculate_gain('relu'))
                nn.init.xavier_uniform_(self.comps, gain=nn.init.calculate_gain('relu'))
            else:
                nn.init.xavier_uniform_(self.weights, gain=nn.init.calculate_gain('relu'))

            if self.bias is not None:
                torch.nn.init.zeros_(self.bias)
        elif reset_mode == 'uniform':
            stdv = 1.0 / math.sqrt(self.weights.size(1))
            if self.weight_decomp == 'block':
                self.blocks.data.uniform_(-stdv, stdv)
            elif self.weight_decomp == 'basis':
                self.bases.data.uniform_(-stdv, stdv)
                self.comps.data.uniform_(-stdv, stdv)
            else:
                self.weights.data.uniform_(-stdv, stdv)

            if self.bias is not None:
                self.bias.data.uniform_(-stdv, stdv)
        else:
            raise NotImplementedError(f'{reset_mode} parameter initialisation method has not been implemented')

    def forward(self, triples, features=None):
        """ Perform a single pass of message propagation """

        assert (features is None) == (self.in_features is None), \
            "Layer has not been properly configured to take in features!"

        if self.weight_decomp is None:
            weights = self.weights
        elif self.weight_decomp == 'basis':
            weights = torch.einsum('rb, bio -> rio', self.comps, self.bases)
        elif self.weight_decomp == 'block':
            weights = block_diag(self.blocks)
        else:
            raise NotImplementedError(f'{self.weight_decomp} decomposition has not been implemented')

        in_dim = self.in_features if self.in_features is not None else self.num_nodes
        out_dim = self.out_features
        num_nodes = self.num_nodes
        num_relations = self.num_relations
        vertical_stacking = self.vertical_stacking
        original_num_relations = int((self.num_relations-1)/2)  # Count without inverse and self-relations
        device = 'cuda' if weights.is_cuda else 'cpu'  # Note: Using cuda status of weights as proxy to decide device

        # Edge dropout on self-loops
        if self.training:
            self_loop_keep_prob = 1 - self.edge_dropout["self_loop"]
        else:
            self_loop_keep_prob = 1

        with torch.no_grad():
            # Add inverse relations
            inverse_triples = generate_inverses(triples, original_num_relations)
            # Add self-loops to triples
            self_loop_triples = generate_self_loops(
                triples, num_nodes, original_num_relations, self_loop_keep_prob, device=device)
            triples_plus = torch.cat([triples, inverse_triples, self_loop_triples], dim=0)

        # Stack adjacency matrices (vertically/horizontally)
        adj_indices, adj_size = stack_matrices(
            triples_plus,
            num_nodes,
            num_relations,
            vertical_stacking=vertical_stacking,
            device=device
        )

        num_triples = adj_indices.size(0)
        vals = torch.ones(num_triples, dtype=torch.float, device=device)

        assert vals.size(0) == (triples.size(0) + inverse_triples.size(0) + self_loop_triples.size(0))

        # Apply normalisation (vertical-stacking -> row-wise rum & horizontal-stacking -> column-wise sum)
        sums = sum_sparse(adj_indices, vals, adj_size, row_normalisation=vertical_stacking, device=device)
        if not vertical_stacking:
            # Rearrange column-wise normalised value to reflect original order (because of transpose-trick)
            n = triples.size(0)
            i = self_loop_triples.size(0)
            sums = torch.cat([sums[n : 2*n], sums[:n], sums[-i:]], dim=0)
        vals = vals / sums

        # Construct adjacency matrix
        if device == 'cuda':
            adj = torch.cuda.sparse.FloatTensor(indices=adj_indices.t(), values=vals, size=adj_size)
        else:
            adj = torch.sparse.FloatTensor(indices=adj_indices.t(), values=vals, size=adj_size)

        assert weights.size() == (num_relations, in_dim, out_dim)

        if self.in_features is None:
            # Featureless
            output = torch.mm(adj, weights.view(num_relations * in_dim, out_dim))
        elif self.vertical_stacking:
            # Adjacency matrix vertically stacked
            af = torch.spmm(adj, features)
            af = af.view(self.num_relations, self.num_nodes, in_dim)
            output = torch.einsum('rio, rni -> no', weights, af)
        else:
            # Adjacency matrix horizontally stacked
            fw = torch.einsum('ni, rio -> rno', features, weights).contiguous()
            output = torch.mm(adj, fw.view(self.num_relations * self.num_nodes, out_dim))

        assert output.size() == (self.num_nodes, out_dim)

        if self.bias is not None:
            output = torch.add(output, self.bias)

        return output


class GraphConvolution(Module):
    """
    Simple GCN layer, similar to https://arxiv.org/abs/1609.02907

    Source: https://github.com/tkipf/pygcn
    """

    def __init__(self, in_features, out_features, bias=True):
        super(GraphConvolution, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.weight = Parameter(torch.Tensor(in_features, out_features))
        if bias:
            self.bias = Parameter(torch.Tensor(out_features))
        else:
            self.register_parameter('bias', None)
        self.reset_parameters()

    def reset_parameters(self):
        stdv = 1. / math.sqrt(self.weight.size(1))
        self.weight.data.uniform_(-stdv, stdv)
        if self.bias is not None:
            self.bias.data.uniform_(-stdv, stdv)

    def forward(self, input, adj):
        support = torch.matmul(input, self.weight)
        output = torch.matmul(adj, support)
        if self.bias is not None:
            return output + self.bias
        else:
            return output

    def __repr__(self):
        return self.__class__.__name__ + ' (' \
               + str(self.in_features) + ' -> ' \
               + str(self.out_features) + ')'
               