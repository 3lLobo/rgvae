import pytest
from utils import no_zero, check_adj_logic, torch_batch_dot, torch_batch_dot_v2, replace_nan, replace_inf, add_e7
import torch

def test_no_zero():
    t = torch.tensor((0.,1.,0.))
    assert no_zero(t).numpy().any() != 0.
    assert no_zero(t).numpy().any() == 1.

def test_torch_batch_dot():
    a = torch.rand([2,3,3,1])
    b = torch.rand([2,5,5,1])
    assert torch_batch_dot(a,b,-1,-1).shape == torch.Size((2,3,3,5,5))

def test_torch_batch_dot_v2():
    a = torch.rand([2,3,5])
    b = torch.rand([2,5,7])
    assert torch_batch_dot_v2(a,b,-1,-2,(2,3,7)).shape == torch.Size((2,3,7))
    

def test_replace_nan():
    my_nan = torch.tensor((1e-11,1e-16))
    assert torch.isnan(replace_nan(my_nan)).any() == False

def test_replace_inf():
    my_inf = torch.tensor((1e11,1e16))
    assert torch.isinf(replace_inf(my_inf)).any() == False

test_no_zero()
test_replace_nan()
test_replace_inf()
test_torch_batch_dot
test_torch_batch_dot_v2
