"""
Utile functions for link prediction.
"""
import gzip, os, pickle, tqdm
import torch
import numpy as np
import pandas as pd
import random
import torch, os, sys, time, tqdm
from torch.autograd import Variable
import torch.nn.functional as F
from collections.abc import Iterable
from torch import nn
import re


def locate_file(filepath):
    directory = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return directory + '/rgvae/' + filepath


def load_strings(file):
    """ Read triples from file """
    with open(file, 'r') as f:
        return [line.split() for line in f]

def load_link_prediction_data(name, use_test_set=False, limit=None):
    """
    Load knowledge graphs for relation Prediction  experiment.
    Source: https://github.com/pbloem/gated-rgcn/blob/1bde7f28af8028f468349b2d760c17d5c908b58b/kgmodels/data.py#L218
    :param name: Dataset name ('aifb', 'am', 'bgs' or 'mutag')
    :param use_test_set: If true, load the canonical test set, otherwise load validation set from file.
    :param limit: If set, only the first n triples are used.
    :return: Relation prediction test and train sets:
              - train: list of edges [subject, predicate object]
              - test: list of edges [subject, predicate object]
              - all_triples: sets of tuples (subject, predicate object)
    """

    if name.lower() == 'fb15k':
        train_file = locate_file('data/fb15k/train.txt')
        val_file = locate_file('data/fb15k/valid.txt')
        test_file = locate_file('data/fb15k/test.txt')
    elif name.lower() == 'fb15k-237':
        train_file = locate_file('data/fB15k-237/train.txt')
        val_file = locate_file('data/fB15k-237/valid.txt')
        test_file = locate_file('data/fB15k-237/test.txt')
    elif name.lower() == 'wn18':
        train_file = locate_file('data/wn18/train.txt')
        val_file = locate_file('data/wn18/valid.txt')
        test_file = locate_file('data/wn18/test.txt')
    elif name.lower() == 'wn18rr':
        train_file = locate_file('data/wn18rr/train.txt')
        val_file = locate_file('data/wn18rr/valid.txt')
        test_file = locate_file('data/wn18rr/test.txt')
    else:
        raise ValueError(f'Could not find \'{name}\' dataset')

    train = load_strings(train_file)
    val = load_strings(val_file)
    test = load_strings(test_file)

    if use_test_set:
        train = train + val
    else:
        test = val

    if limit:
        train = train[:limit]
        test = test[:limit]

    # Mappings for nodes (n) and relations (r)
    nodes, rels = set(), set()
    for i in train + val + test:
      if len(i) < 3:
        print(i)
    for s, p, o in train + test:
        nodes.add(s)
        rels.add(p)
        nodes.add(o)

    i2n, i2r = list(nodes), list(rels)
    n2i, r2i = {n: i for i, n in enumerate(nodes)}, {r: i for i, r in enumerate(rels)}

    all_triples = set()
    for s, p, o in train + test:
        all_triples.add((n2i[s], r2i[p], n2i[o]))

    train = [[n2i[st[0]], r2i[st[1]], n2i[st[2]]] for st in train]
    test = [[n2i[st[0]], r2i[st[1]], n2i[st[2]]] for st in test]

    return (n2i, i2n), (r2i, i2r), train, test, all_triples

def triple2matrix(triples, max_n: int, max_r: int):
    """
    Transforms triples into matrix form.
    Params:
        triples: set of sparse triples
        max_n: total count of nodes
        max_t: total count of relations
    Outputs the A,E,F matrices for the input triples,
    """
    # An exception for single triples.
    triples = triples.detach().cpu().numpy()
    n_list = list(dict.fromkeys([triple[0] for triple in triples]))+list(dict.fromkeys([triple[2] for triple in triples]))
    n_dict =  dict(zip(n_list, np.arange(len(n_list))))
    n = 2*len(triples)     # All matrices must be of same size

    # The empty first dimension is to stacking into batches.
    
    A = torch.zeros((1,n,n), device=d())
    E = torch.zeros((1,n,n,max_r), device=d())
    F = torch.zeros((1,n,max_n), device=d())

    for (s, r, o) in triples:
        i_s, i_o = n_dict[s], n_dict[o]
        A[0,i_s,i_o] = 1
        E[0,i_s,i_o,r] = 1
        F[0,i_s,s] = 1
        F[0,i_o,o] = 1
    return (A, E, F)

def matrix2triple(graph):
    """
    Converts a sparse graph back to triple from.
    Args:
        graph: Graph consisting of A, E, F matrix
    returns a set of triples/one triple.
    """
    A, E, F = graph
    a = A.squeeze().detach().cpu().numpy()
    e = E.squeeze().detach().cpu().numpy()
    f = F.squeeze().detach().cpu().numpy()
    
    s, o = np.where(a == 1)
    
    triples = list()
    for i in range(len(s)):
        if len(e.shape) == 2:
            r = e[s[i],o[i]]
        else:
            cho = np.where(e[s[i],o[i],:] == 1)[0]
            if cho.size > 0:
                r = np.array(np.random.choice(cho[0]))
            else:
                print('No attribute prediction for node {},{}. Graph inconsistent!'.format(s[i],o[i]))
                break
        if r.size > 0:
            triple = (f[s[i]], r, f[o[i]])
            triples.append(triple)
    return triples


def translate_triple(triples, i2n, i2r, entity_dict):
    """
    Translate an indexed triple back to text.
    Args:
    ....
    """

    triples_text = list()
    for triple in triples:
        (s,r,o) = triple
        triples_text.append((entity_dict[i2n[s]][0], i2r[r], entity_dict[i2n[o]][0]))
    return triples_text


def batch_t2m(batch, n: int, n_e: int, n_r: int):
    """
    Converts batches of triples into matrix form.

    :param batch: batch of triples
    :param n: number of triples per. matrix
    :param n_e: total node count.
    :param n_r: total edge attribute count.
    :return: the batched matrices A, E, F.
    """
    # This condition is needed for batch size = 1.
    if len(batch.shape) > 1:
        bs = batch.shape[0]
    else:
        bs = 1
        batch = batch.unsqueeze(0)
    batch_a = list()
    batch_e = list()
    batch_f = list()
    for ii in range(bs):
        (A, E, F) = triple2matrix(batch[ii:ii+n,:], n_e, n_r)
        assert A.shape[1] != 1
        batch_a.append(A)
        batch_e.append(E)
        batch_f.append(F)

    return [torch.cat(batch_a, dim=0),torch.cat(batch_e, dim=0),torch.cat(batch_f, dim=0)]

###################### For actual link prediction ###########################

tics = []

def prt(verbose, *args, **kwargs):
    if verbose:
        print(*args, **kwargs)

def filter(rawtriples, all, true):
    filtered = []

    for triple in rawtriples:
        if triple == true or not triple in all:
            filtered.append(triple)

    return filtered


def filter_scores_(scores, batch, truedicts, head=True):
    """
    Filters a score matrix by setting the scores of known non-target true triples to -inf
    :param scores:
    :param batch:
    :param truedicts:
    :param head:
    :return:
    """

    indices = [] # indices of triples whose scores should be set to -infty

    heads, tails = truedicts

    for i, (s, p, o) in enumerate(batch):
        s, p, o = triple = (s.item(), p.item(), o.item())
        if head:
            indices.extend([(i, si) for si in heads[p, o] if si != s])
        else:
            indices.extend([(i, oi) for oi in tails[s, p] if oi != o])
        #-- We add the indices of all know triples except the one corresponding to the target triples.

    indices = torch.tensor(indices, device=d())

    if indices.shape[0] != 0:
        scores[indices[:, 0], indices[:, 1]] = float('-inf')

def truedicts(all):
    """
    Generates a pair of dictionairies containg all true tail and head completions.
    :param all: A list of 3-tuples containing all known true triples
    :return:
    """
    heads, tails = {(p, o) : [] for _, p, o in all}, {(s, p) : [] for s, p, _ in all}

    for s, p, o in all:
        heads[p, o].append(s)
        tails[s, p].append(o)

    return heads, tails

def eval(model : nn.Module, valset, truedicts, n, r, batch_size=16, hitsat=[1, 3, 10], filter_candidates=True, verbose=False, elbo=True):
    """
    Evaluates a triple scoring model. Does the sorting in a single, GPU-accelerated operation.
    :param model:
    :param val_set:
    :param alltriples:
    :param filter:
    :param eblo: If true, use full elbo as loss. Else just the reconstruction loss.
    :return:
    """

    rng = tqdm.trange if verbose else range

    heads, tails = truedicts

    tforward = tfilter = tsort = 0.0

    tic()
    ranks = []
    head = False            # TODO change this back later to do both head tail
    # for head in tqdm.tqdm([True, False], desc='LP Head, Tail', leave=True):  # head or tail prediction

    for fr in rng(0, valset.shape[0], batch_size, desc='Validation Set', leave=True):
        to = min(fr + batch_size, valset.shape[0])

        batch = valset[fr:to, :].to(device=d())
        bn, _ = batch.size()

        # compute the full score matrix (filter later)
        bases   = batch[:, 1:] if head else batch[:, :2]
        targets = batch[:, 0]  if head else batch[:, 2]

        # collect the triples for which to compute scores
        bexp = bases.view(bn, 1, 2).expand(bn, n, 2)
        ar   = torch.arange(n, device=d()).view(1, n, 1).expand(bn, n, 1)
        toscore = torch.cat([ar, bexp] if head else [bexp, ar], dim=2)
        assert toscore.size() == (bn, n, 3)

        tic()
        scores = list()
        for ii in rng(0, bn, 1, desc='Valset Batch', leave=False):
            batch_scores = list()
            for iii in rng(0, n, batch_size, desc='Batch of Batch', leave=False):
                tt = min(iii + batch_size, toscore.shape[1])
                tpg = model.n -1    # number of triples per graph
                sub_batch = batch_t2m(toscore[ii, iii:tt, :].squeeze(), tpg, n, r)
                if elbo:
                    loss = model.elbo(sub_batch)
                else:
                    prediction = model.forward(sub_batch)
                    loss = model.reconstruction_loss(sub_batch, prediction)
                batch_scores.append(loss)
            scores.append(torch.cat(batch_scores, dim=0).unsqueeze(0))
        scores = torch.cat(scores, dim=0).squeeze()
        tforward += toc()
        assert scores.size() == (bn, n)

        # filter out the true triples that aren't the target
        tic()
        filter_scores_(scores, batch, truedicts, head=head)
        tfilter += toc()

        # Select the true scores, and count the number of values larger than than
        true_scores = scores[torch.arange(bn, device=d()), targets]
        raw_ranks = torch.sum(scores > true_scores.view(bn, 1), dim=1, dtype=torch.long)
        # -- This is the "optimistic" rank (assuming it's sorted to the front of the ties)
        num_ties = torch.sum(scores == true_scores.view(bn, 1), dim=1, dtype=torch.long)

        # Account for ties (put the true example halfway down the ties)
        branks = raw_ranks + (num_ties - 1) // 2

        ranks.extend((branks + 1).tolist())

    mrr = sum([1.0/rank for rank in ranks])/len(ranks)

    hits = []
    for k in hitsat:
        hits.append(sum([1.0 if rank <= k else 0.0 for rank in ranks]) / len(ranks))

    # if verbose:
    #     print(f'time {toc():.4}s total, {tforward:.4}s forward, {tfilter:.4}s filtering, {tsort:.4}s sorting.')

    return mrr, tuple(hits), ranks

def tic():
    tics.append(time.time())

def toc():
    if len(tics)==0:
        return None
    else:
        return time.time()-tics.pop()

def mask_(matrices, maskval=0.0, mask_diagonal=True):
    """
    Masks out all values in the given batch of matrices where i <= j holds,
    i < j if mask_diagonal is false
    In place operation
    :param tns:
    :return:
    """

    b, h, w = matrices.size()

    indices = torch.triu_indices(h, w, offset=0 if mask_diagonal else 1)
    matrices[:, indices[0], indices[1]] = maskval

def d(tensor=None):
    """
    Returns a device string either for the best available device,
    or for the device corresponding to the argument
    :param tensor:
    :return:
    """
    if tensor is None:
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    if type(tensor) == bool:
        return 'cuda'if tensor else 'cpu'
    return 'cuda' if tensor.is_cuda else 'cpu'

def here(subpath=None):
    """
    :return: the path in which the package resides (the directory containing the 'kgmodels' dir)
    """
    if subpath is None:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))

    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', subpath))

def adj(edges, num_nodes, cuda=False, vertical=True):
    """
    Computes a sparse adjacency matrix for the given graph (the adjacency matrices of all
    relations are stacked vertically).
    :param edges: Dictionary representing the edges
    :param i2r: list of relations
    :param i2n: list of nodes
    :return: sparse tensor
    """
    ST = torch.cuda.sparse.FloatTensor if cuda else torch.sparse.FloatTensor

    r, n = len(edges.keys()), num_nodes
    size = (r*n, n) if vertical else (n, r*n)

    from_indices = []
    upto_indices = []

    for rel, (fr, to) in edges.items():

        offset = rel * n

        if vertical:
            fr = [offset + f for f in fr]
        else:
            to = [offset + t for t in to]

        from_indices.extend(fr)
        upto_indices.extend(to)

    indices = torch.tensor([from_indices, upto_indices], dtype=torch.long, device=d(cuda))

    assert indices.size(1) == sum([len(ed[0]) for _, ed in edges.items()])
    assert indices[0, :].max() < size[0], f'{indices[0, :].max()}, {size}, {r}, {edges.keys()}'
    assert indices[1, :].max() < size[1], f'{indices[1, :].max()}, {size}, {r}, {edges.keys()}'

    return indices.t(), size

def adj_triples(triples, num_nodes, num_rels, cuda=False, vertical=True):
    """
    Computes a sparse adjacency matrix for the given graph (the adjacency matrices of all
    relations are stacked vertically).
    :param edges: List representing the triples
    :param i2r: list of relations
    :param i2n: list of nodes
    :return: sparse tensor
    """
    r, n = num_rels, num_nodes
    size = (r*n, n) if vertical else (n, r*n)

    from_indices = []
    upto_indices = []

    for fr, rel, to in triples:

        offset = rel.item() * n

        if vertical:
            fr = offset + fr.item()
        else:
            to = offset + to.item()

        from_indices.append(fr)
        upto_indices.append(to)

    tic()
    indices = torch.tensor([from_indices, upto_indices], dtype=torch.long, device=d(cuda))

    assert indices.size(1) == len(triples)
    assert indices[0, :].max() < size[0], f'{indices[0, :].max()}, {size}, {r}'
    assert indices[1, :].max() < size[1], f'{indices[1, :].max()}, {size}, {r}'

    return indices.t(), size

def adj_triples_tensor(triples, num_nodes, num_rels, vertical=True):
    """
    Computes a sparse adjacency matrix for the given graph (the adjacency matrices of all
    relations are stacked vertically).
    :param edges: List representing the triples
    :param i2r: list of relations
    :param i2n: list of nodes
    :return: sparse tensor
    """
    assert triples.dtype == torch.long

    r, n = num_rels, num_nodes
    size = (r*n, n) if vertical else (n, r*n)

    fr, to = triples[:, 0], triples[:, 2]
    offset = triples[:, 1] * n
    if vertical:
        fr = offset + fr
    else:
        to = offset + to

    indices = torch.cat([fr[:, None], to[:, None]], dim=1)

    assert indices.size(0) == triples.size(0)
    assert indices[:, 0].max() < size[0], f'{indices[0, :].max()}, {size}, {r}'
    assert indices[:, 1].max() < size[1], f'{indices[1, :].max()}, {size}, {r}'

    return indices, size

def sparsemm(use_cuda):
    """
    :param use_cuda:
    :return:
    """

    return SparseMMGPU.apply if use_cuda else SparseMMCPU.apply

class SparseMMCPU(torch.autograd.Function):

    """
    Sparse matrix multiplication with gradients over the value-vector
    Does not work with batch dim.
    """

    @staticmethod
    def forward(ctx, indices, values, size, xmatrix):

        # print(type(size), size, list(size), intlist(size))
        # print(indices.size(), values.size(), torch.Size(intlist(size)))

        matrix = torch.sparse.FloatTensor(indices, values, torch.Size(intlist(size)))

        ctx.indices, ctx.matrix, ctx.xmatrix = indices, matrix, xmatrix

        return torch.mm(matrix, xmatrix)

    @staticmethod
    def backward(ctx, grad_output):
        grad_output = grad_output.data

        # -- this will break recursive autograd, but it's the only way to get grad over sparse matrices

        i_ixs = ctx.indices[0,:]
        j_ixs = ctx.indices[1,:]
        output_select = grad_output[i_ixs, :]
        xmatrix_select = ctx.xmatrix[j_ixs, :]

        grad_values = (output_select * xmatrix_select).sum(dim=1)

        grad_xmatrix = torch.mm(ctx.matrix.t(), grad_output)
        return None, Variable(grad_values), None, Variable(grad_xmatrix)

class SparseMMGPU(torch.autograd.Function):

    """
    Sparse matrix multiplication with gradients over the value-vector
    Does not work with batch dim.
    """

    @staticmethod
    def forward(ctx, indices, values, size, xmatrix):

        # print(type(size), size, list(size), intlist(size))

        matrix = torch.cuda.sparse.FloatTensor(indices, values, torch.Size(intlist(size)))

        ctx.indices, ctx.matrix, ctx.xmatrix = indices, matrix, xmatrix

        return torch.mm(matrix, xmatrix)

    @staticmethod
    def backward(ctx, grad_output):
        grad_output = grad_output.data

        # -- this will break recursive autograd, but it's the only way to get grad over sparse matrices

        i_ixs = ctx.indices[0,:]
        j_ixs = ctx.indices[1,:]
        output_select = grad_output[i_ixs]
        xmatrix_select = ctx.xmatrix[j_ixs]

        grad_values = (output_select *  xmatrix_select).sum(dim=1)

        grad_xmatrix = torch.mm(ctx.matrix.t(), grad_output)
        return None, Variable(grad_values), None, Variable(grad_xmatrix)

def spmm(indices, values, size, xmatrix):

    cuda = indices.is_cuda

    sm = sparsemm(cuda)
    return sm(indices.t(), values, size, xmatrix)

class Lambda(nn.Module):
    def __init__(self, lambd):
        super(Lambda, self).__init__()
        self.lambd = lambd
    def forward(self, x):
        return self.lambd(x)

class Debug(nn.Module):
    def __init__(self, lambd):
        super(Debug, self).__init__()
        self.lambd = lambd
    def forward(self, x):
        self.lambd(x)
        return x

def batchmm(indices, values, size, xmatrix, cuda=None):
    """
    Multiply a batch of sparse matrices (indices, values, size) with a batch of dense matrices (xmatrix)
    :param indices:
    :param values:
    :param size:
    :param xmatrix:
    :return:
    """

    if cuda is None:
        cuda = indices.is_cuda

    b, n, r = indices.size()
    dv = 'cuda' if cuda else 'cpu'

    height, width = size

    size = torch.tensor(size, device=dv, dtype=torch.long)

    bmult = size[None, None, :].expand(b, n, 2)
    m = torch.arange(b, device=dv, dtype=torch.long)[:, None, None].expand(b, n, 2)

    bindices = (m * bmult).view(b*n, r) + indices.view(b*n, r)

    bfsize = Variable(size * b)
    bvalues = values.contiguous().view(-1)

    b, w, z = xmatrix.size()
    bxmatrix = xmatrix.view(-1, z)

    sm = sparsemm(cuda)

    result = sm(bindices.t(), bvalues, bfsize, bxmatrix)

    return result.view(b, height, -1)


def sum_sparse(indices, values, size, row=True):
    """
    Sum the rows or columns of a sparse matrix, and redistribute the
    results back to the non-sparse row/column entries
    Arguments are interpreted as defining sparse matrix. Any extra dimensions
    are treated as batch.
    :return:
    """

    assert len(indices.size()) == len(values.size()) + 1

    if len(indices.size()) == 2:
        # add batch dim
        indices = indices[None, :, :]
        values = values[None, :]
        bdims = None
    else:
        # fold up batch dim
        bdims = indices.size()[:-2]
        k, r = indices.size()[-2:]
        assert bdims == values.size()[:-1]
        assert values.size()[-1] == k

        indices = indices.view(-1, k, r)
        values = values.view(-1, k)

    b, k, r = indices.size()

    if not row:
        # transpose the matrix
        indices = torch.cat([indices[:, :, 1:2], indices[:, :, 0:1]], dim=2)
        size = size[1], size[0]

    ones = torch.ones((size[1], 1), device=d(indices))

    s, _ = ones.size()
    ones = ones[None, :, :].expand(b, s, 1).contiguous()

    # print(indices.size(), values.size(), size, ones.size())
    # sys.exit()

    sums = batchmm(indices, values, size, ones) # row/column sums
    bindex = torch.arange(b, device=d(indices))[:, None].expand(b, indices.size(1))
    sums = sums[bindex, indices[:, :, 0], 0]

    if bdims is None:
        return sums.view(k)

    return sums.view(*bdims + (k,))


def intlist(tensor):
    """
    A slow and stupid way to turn a tensor into an iterable over ints
    :param tensor:
    :return:
    """
    if type(tensor) is list or type(tensor) is tuple:
        return tensor

    tensor = tensor.squeeze()

    assert len(tensor.size()) == 1

    s = tensor.size()[0]

    l = [None] * s
    for i in range(s):
        l[i] = int(tensor[i])

    return l


def simple_normalize(indices, values, size, row=True, method='softplus', cuda=torch.cuda.is_available()):
    """
    Simple softmax-style normalization with
    :param indices:
    :param values:
    :param size:
    :param row:
    :return:
    """
    epsilon = 1e-7

    if method == 'softplus':
        values = F.softplus(values)
    elif method == 'abs':
        values = values.abs()
    elif method == 'relu':
        values = F.relu(values)
    else:
        raise Exception(f'Method {method} not recognized')

    sums = sum_sparse(indices, values, size, row=row)

    return (values/(sums + epsilon))

# -- stable(ish) softmax
def logsoftmax(indices, values, size, its=10, p=2, method='iteration', row=True, cuda=torch.cuda.is_available()):
    """
    Row or column log-softmaxes a sparse matrix (using logsumexp trick)
    :param indices:
    :param values:
    :param size:
    :param row:
    :return:
    """
    epsilon = 1e-7

    if method == 'naive':
        values = values.exp()
        sums = sum_sparse(indices, values, size, row=row)

        return (values/(sums + epsilon)).log()

    if method == 'pnorm':
        maxes = rowpnorm(indices, values, size, p=p)
    elif method == 'iteration':
        maxes = itmax(indices, values, size,its=its, p=p)
    else:
        raise Exception('Max method {} not recognized'.format(method))

    mvalues = torch.exp(values - maxes)

    sums = sum_sparse(indices, mvalues, size, row=row)  # row/column sums]

    return mvalues.log() - sums.log()

def rowpnorm(indices, values, size, p, row=True):
    """
    Row or column p-norms a sparse matrix
    :param indices:
    :param values:
    :param size:
    :param row:
    :return:
    """
    pvalues = torch.pow(values, p)
    sums = sum_sparse(indices, pvalues, size, row=row)

    return torch.pow(sums, 1.0/p)

def itmax(indices, values, size, its=10, p=2, row=True):
    """
    Iterative computation of row max
    :param indices:
    :param values:
    :param size:
    :param p:
    :param row:
    :param cuda:
    :return:
    """

    epsilon = 0.00000001

    # create an initial vector with all values made positive
    # weights = values - values.min()
    weights = F.softplus(values)
    weights = weights / (sum_sparse(indices, weights, size) + epsilon)

    # iterate, weights converges to a one-hot vector
    for i in range(its):
        weights = weights.pow(p)

        sums = sum_sparse(indices, weights, size, row=row)  # row/column sums
        weights = weights/sums

    return sum_sparse(indices, values * weights, size, row=row)

def schedule(epoch, schedule):
    """
    Provides a piecewise linear schedule for some parameter
    :param epoch:
    :param schedule: Dictionary of integer key and floating point value pairs
    :return:
    """

    schedule = [(k, v) for k, v in schedule.items()]
    schedule = sorted(schedule, key = lambda x : x[0])

    for i, (k, v) in enumerate(schedule):

        if epoch <= k:
            if i == 0:
                return v
            else:
                # interpolate between i-1 and 1

                kl, vl = schedule[i-1]
                rng = k - kl

                prop = (epoch - kl) / rng
                propl = 1.0 - prop

                return propl * vl + prop * v

    return v

def contains_nan(input):
    if (not isinstance(input, torch.Tensor)) and isinstance(input, Iterable):
        for i in input:
            if contains_nan(i):
                return True
        return False
    else:
        return bool(torch.isnan(input).sum() > 0)
#
def contains_inf(input):
    if (not isinstance(input, torch.Tensor)) and isinstance(input, Iterable):
        for i in input:
            if contains_inf(i):
                return True
        return False
    else:
        return bool(torch.isinf(input).sum() > 0)

def block_diag(m):
    """
    courtesy of: https://gist.github.com/yulkang/2e4fc3061b45403f455d7f4c316ab168
    Make a block diagonal matrix along dim=-3
    EXAMPLE:
    block_diag(torch.ones(4,3,2))
    should give a 12 x 8 matrix with blocks of 3 x 2 ones.
    Prepend batch dimensions if needed.
    You can also give a list of matrices.
    :type m: torch.Tensor, list
    :rtype: torch.Tensor
    """

    if type(m) is list:
        m = torch.cat([m1.unsqueeze(-3) for m1 in m], -3)

    dim = m.dim()
    n = m.shape[-3]

    siz0 = m.shape[:-3]
    siz1 = m.shape[-2:]

    m2 = m.unsqueeze(-2)

    eye = attach_dim(torch.eye(n, device=d(m)).unsqueeze(-2), dim - 3, 1)

    return (m2 * eye).reshape(
        siz0 + torch.Size(torch.tensor(siz1) * n)
    )

def attach_dim(v, n_dim_to_prepend=0, n_dim_to_append=0):
    return v.reshape(
        torch.Size([1] * n_dim_to_prepend)
        + v.shape
        + torch.Size([1] * n_dim_to_append))

def prod(array):

    p = 1
    for e in array:
        p *= e
    return p

def batch(model, *inputs, batch_size=16, **kwargs):
    """
    Batch forward.
    :param model: multiple input, single output
    :param inputs: should all have the same 0 dimension
    :return:
    """

    n = inputs[0].size(0)

    outs = []
    for fr in range(0, n, batch_size):
        to = min(n, fr + batch_size)

        batches = [inp[fr:to] for inp in inputs]

        if torch.cuda.is_available():
            batches = [btc.cuda() for btc in batches]

        outs.append(model(*batches, **kwargs).cpu())

    return torch.cat(outs, dim=0)

def get_slug(s):
    """
    Returns a simplified version of the given string that can serve as a filename or directory name.
    :param s:
    :return:
    """
    s = str(s).strip().replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', s)