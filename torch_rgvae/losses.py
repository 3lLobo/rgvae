"""
Collection of loss functions.
"""
from graph_matching.MPGM import MPGM
from utils.utils import *
import wandb, torch
import torch.nn as nn


def graph_CEloss(target, prediction, softmax_E: bool=True, l_A=1., l_E=1., l_F=1.):
    """
    Cross entropy loss function for the predicted graph. The loss for each matrix is computed separately.
    Args:
        target: list of the 3 target matrices A, E, F.
        prediction: list of the 3 predicted matrices A_hat, E_hat, F_hat.
        l_A: weight for BCE of A
        l_E: weight for BCE or CE of E
        l_F: weight for CE of F
        softmax_E: use CE for E
    """
    # Cast target vectors to tensors.
    A, E, F = target
    A_hat, E_hat, F_hat = prediction

    # Define loss function
    bce = torch.nn.BCELoss()
    cce = torch.nn.CrossEntropyLoss()
    sigmoid = nn.Sigmoid()

    if softmax_E:
        log_p_E = l_E*cce(E_hat.permute(0,3,1,2), torch.argmax(E, -1, keepdim=False))
    else:
        log_p_E = l_E*bce(sigmoid(E_hat), E)
        
    log_p_A = l_A*bce(sigmoid(A_hat), A)
    log_p_F = l_F*cce(F_hat.permute(0,2,1), torch.argmax(F, -1, keepdim=False))

    # Weight and add loss
    log_p = - log_p_A - log_p_E - log_p_F

    x_permute = torch.ones_like(A)          # Just a placeholder
    wandb.log({"recon_loss_mean": log_p.detach().cpu().numpy(), "recon_loss_A_mean": log_p_A.detach().cpu().numpy(),
             "recon_loss_E_mean": log_p_E.detach().cpu().numpy(), "recon_loss_F_mean": log_p_F.detach().cpu().numpy()})
    return log_p, x_permute


def mpgm_loss(target, prediction, l_A=1., l_E=1., l_F=1., zero_diag: bool=False, softmax_E: bool=True):
    """
    Modification of the loss function described in the GraphVAE paper.
    The difference is, we treat A and E the same as both are sigmoided and F stays as it is softmaxed.
    This way we can have multiple edge attributes.
    The node attribute matrix is used to index the nodes, therefore the softmax.
    Args:
        target: list of the 3 target matrices A, E, F.
        prediction: list of the 3 predicted matrices A_hat, E_hat, F_hat.
        l_A: weight for BCE of A
        l_E: weight for BCE of E
        l_F: weight for BCE of F
        zero_diag: if to zero out the diagonal in log_A term_3 and log_E.
    """

    A, E, F = target

    A_hat, E_hat, F_hat = prediction
    bs = A.shape[0]
    n = A.shape[1]
    k = A_hat.shape[1]
    d_e = E.shape[-1]

    mpgm = MPGM()
    sigmoid = nn.Sigmoid()
    softmax = nn.Softmax(dim=-1)
    A_hat = sigmoid(A_hat)
    if softmax_E:
        E_hat = softmax(E_hat)
    else:
        E_hat = sigmoid(E_hat)
    F_hat = softmax(F_hat)
    
    X = mpgm.call(A, A_hat.detach(), E, E_hat.detach(), F, F_hat.detach())

    # This is the loss part from the paper:
    A_t = torch.transpose(X, 2, 1) @ A @ X     # shape (bs,k,n)
    E_t = torch_batch_dot_v2(torch_batch_dot_v2(X, E, 1, 1, [bs,n,k,d_e]), X, -2, 1, [bs,k,k,d_e])    # target shape is (bs,k,k,d_e)
    E_hat_t = torch_batch_dot_v2(torch_batch_dot_v2(X, E_hat, -1, 1, [bs,n,k,d_e]), X, -2, 1, [bs,n,n,d_e])
    F_hat_t = torch.matmul(X, F_hat)

    term_1 = (1/k) * torch.sum(torch.diagonal(A_t, dim1=-2, dim2=-1) * torch.log(torch.diagonal(A_hat, dim1=-2, dim2=-1)), -1, keepdim=True)
    A_t_diag = torch.diagonal(A_t, dim1=-2, dim2=-1)
    A_hat_diag = torch.diagonal(A_hat, dim1=-2, dim2=-1)
    term_2 = (1/k) * torch.sum((torch.ones_like(A_t_diag) - A_t_diag) * torch.log((torch.ones_like(A_hat_diag) - A_hat_diag)), -1, keepdim=True)

    """
    Thought: Lets compare w/ against w/o the zeroing out diagonal and see what happens.
    """
    # log_p_A part. Split in multiple terms for clarity.
    term_31 = A_t * torch.log(A_hat)
    term_32 = (1. - A_t) * torch.log(1. - A_hat)
    # Zero diagonal mask:
    mask = torch.ones_like(term_32)
    # The number of edges we are taking into account.
    a_edges = k*k
    if zero_diag:
        ind = np.diag_indices(mask.shape[-1])
        mask[:,ind[0], ind[1]] = 0
        a_edges = (k*(k-1))
    term_3 = (1/a_edges) * torch.sum((term_31 + term_32) * mask, [1,2]).unsqueeze(-1)
    log_p_A = term_1 + term_2 + term_3

    # log_p_F  
    log_p_F = (1/n) * torch.sum(torch.log(no_zero(torch.sum(F * F_hat_t, -1))), (-1)).unsqueeze(-1)

    # log_p_E
    if softmax_E:
        log_p_E = ((1/(torch.norm(A, p=1, dim=[-2,-1]))) * torch.sum(torch.sum(torch.log(no_zero(E * E_hat_t)), -1) * mask, (-2,-1))).unsqueeze(-1)
    else:
        # I changed the factor to the number of edges (k*(k-1)) the -1 is for the zero diagonal.
        k_zero = k
        if zero_diag:
            k_zero = k - 1
        log_p_E = ((1/(k*(k_zero))) * torch.sum(torch.sum(E_t * torch.log(E_hat) + (1 - E_t) * torch.log(1 - E_hat), -1) * mask, (-2,-1))).unsqueeze(-1)

    log_p = l_A * log_p_A + l_E * log_p_E + l_F * log_p_F
    wandb.log({"recon_loss_mean": torch.mean(log_p).detach().cpu().numpy(), "recon_loss_A_mean": torch.mean(l_A * log_p_A).detach().cpu().numpy(),
             "recon_loss_E_mean": torch.mean(l_E * log_p_E).detach().cpu().numpy(), "recon_loss_F_mean": torch.mean(l_F * log_p_F).detach().cpu().numpy(),
             "recon_loss_std": torch.std(log_p).detach().cpu().numpy(), "recon_loss_A_std": torch.std(l_A * log_p_A).detach().cpu().numpy(),
             "recon_loss_E_std": torch.std(l_E * log_p_E).detach().cpu().numpy(), "recon_loss_F_std": torch.std(l_F * log_p_F).detach().cpu().numpy(),})

    return log_p, X


def kl_divergence(mean, logvar, raxis=1):
    """
    KL divergence between N(mean,std) and the standard normal N(0,1).
    Args:
        mean: mean of a normal dist.
        logvar: log variance (log(std**2)) of a normal dist.
    Returns Kl divergence in batch shape.
    """
    kl_term = 1/2 * torch.sum((logvar.exp() + mean.pow(2) - logvar - 1), dim=raxis)
    wandb.log({"reg_loss_mean": torch.mean(kl_term).detach().cpu().numpy(), "reg_loss_std": torch.std(kl_term).detach().cpu().numpy()})
    
    return kl_term.unsqueeze(-1)
