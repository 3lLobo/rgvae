"""
Graph Convolution VAE implementation in pytorch.
The encoder is a graph convolution NN with sparse matrix input of adjacency and edge node attribute matrix.
The decoder a MLP with a flattened normal matrix output.
"""

import time
from torch_rgvae.GVAE import GVAE
from torch_rgvae.encoders import *
from torch_rgvae.decoders import *
import torch.nn as nn
from torch_rgvae.losses import *
from utils.utils import *
from scipy import sparse


class GCVAE(GVAE):
    def __init__(self, args, n_r: int, n_e: int, dataset_name: str):
        """
        Graph Variational Auto Encoder
        :param n : Number of nodes
        :param n_e : Number of node attributes
        :param n_r : Number of edge attributes
        :param dataset_name : name of the dataset which the model will train on.
        :param h_dim : Hidden dimension
        :param z_dim : latent dimension
        :param beta: for beta < 1, makes the model is a beta-VAE
        :param softmax_E : use softmax for edge attributes
        """
        super().__init__(args, n_r, n_e, dataset_name)

        self.name = 'GCVAE'

        n = self.n
        input_dim = n*n + n*n_e + n*n*n_r
        self.input_dim = input_dim
        n_feat = n_e + n * n_r

        self.encoder = GCN(n, n_feat, self.h_dim, 2*self.z_dim).to(torch.double)
        self.decoder = RMLP(input_dim, self.h_dim, self.z_dim)
        
    def encode(self, args_in):
        """
        The encoder predicts a mean and logarithm of std of the prior distribution for the decoder.
        Args:
            A: Adjacency matrix of size n*n
            E: Edge attribute matrix of size n*n*n_r
            F: Node attribute matrix of size n*n_e
        """
        (A, E, F) = args_in
        self.edge_count = torch.norm(A[0], p=1)
        bs = A.shape[0]

        # We reshape E to (bs,n,n*d_e) and then concat it with F
        # features = np.concatenate((np.reshape(E, (bs, self.n, self.n*self.n_r)), F), axis=-1)
        features = torch.cat((torch.reshape(E, (bs, self.n, self.n*self.n_r)), F), -1)
        # features = torch.Tensor(np.array(features))
        return torch.split(self.encoder(features, A), self.z_dim, dim=1)
