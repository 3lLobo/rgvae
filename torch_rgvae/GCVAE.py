"""
Graph Convolution VAE implementation in pytorch.
The encoder is a graph convolution NN with sparse matrix input of adjacency and edge node attribute matrix.
The decoder a MLP with a flattened normal matrix output.
"""

import time
from torch_rgvae.GVAE import TorchGVAE
from torch_rgvae.encoders import *
from torch_rgvae.decoders import *
import torch.nn as nn
from torch_rgvae.losses import *
from utils import *
from scipy import sparse


class GCVAE(TorchGVAE):
    def __init__(self, n: int, ea: int, na: int, h_dim: int=512, z_dim: int=2):
        """
        Graph Variational Auto Encoder
        Args:
            n : Number of nodes
            na : Number of node attributes
            ea : Number of edge attributes
            h_dim : Hidden dimension
            z_dim : latent dimension
        """
        super().__init__(n, ea, na, h_dim, z_dim)

        self.name = 'GCVAE'
        input_dim = n*n + n*na + n*n*ea
        self.input_dim = input_dim
        self.z_dim = z_dim
        n_feat = na + n * ea

        self.encoder = GCN(n, n_feat, h_dim, 2*z_dim).to(torch.double)
        
    def encode(self, args_in):
        """
        The encoder predicts a mean and logarithm of std of the prior distribution for the decoder.
        Args:
            A: Adjacency matrix of size n*n
            E: Edge attribute matrix of size n*n*ea
            F: Node attribute matrix of size n*na
        """
        (A, E, F) = args_in
        self.edge_count = torch.norm(torch.tensor(A[0] * 1.), p=1)
        bs = A.shape[0]

        # We reshape E to (bs,n,n*d_e) and then concat it with F
        features = np.concatenate((np.reshape(E, (bs, self.n, self.n*self.ea)), F), axis=-1)
        adj = torch.tensor(A)
        features = torch.Tensor(np.array(features))
        return torch.split(self.encoder(features, adj), self.z_dim, dim=1)

    def normalize(self, mx):
        """Row-normalize sparse matrix"""
        rowsum = np.array(mx.sum(1))
        r_inv = np.power(rowsum, -1).flatten()
        r_inv[np.isinf(r_inv)] = 0.
        r_mat_inv = sp.diags(r_inv)
        mx = r_mat_inv.dot(mx)
        return mx

    def sparse_mx_to_torch_sparse_tensor(self, sparse_mx):
        """Convert a scipy sparse matrix to a torch sparse tensor."""
        sparse_mx = sparse_mx.tocoo().astype(np.float32)
        indices = torch.from_numpy(
            np.vstack((sparse_mx.row, sparse_mx.col)).astype(np.int64))
        values = torch.from_numpy(sparse_mx.data)
        shape = torch.Size(sparse_mx.shape)
        return torch.sparse.FloatTensor(indices, values, shape)

