import torch
import numpy as np
from torch_rgvae.GVAE import GVAE
from torch_rgvae.GCVAE import GCVAE
from lp_utils import *
from experiments.train_eval_vae import train_eval_vae
from experiments.link_prediction import link_prediction
from datetime import date
import json


# This sets the default torch dtype. Double-power
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Using device:', device)
my_dtype = torch.float64
torch.set_default_dtype(my_dtype)

# Parameters. Arg parsing on its way.
n = 1       # number of triples per matrix ( =  matrix_n/2)
batch_size = 64        # Choose a low batch size for debugging, or creating the dataset will take very long.
h = 60      # number of hidden dimensions
seed = 11
np.random.seed(seed=seed)
torch.manual_seed(seed)
epochs = 111
lr = 1e-6
dataset = 'fb15k'
# model_path = 'data/model/GCVAE_fb15k_69e_20201025.pt'

# Get data
(n2i, i2n), (r2i, i2r), train_set, test_set, all_triples = load_link_prediction_data(dataset)
d_n = len(n2i)
d_e = len(r2i)

# Initialize model and optimizer.
if model_name == 'GCVAE'
    model = GCVAE(n*2, d_e, d_n, z_dim=h).to(device)
else:
    model = GVAE(n*2, d_e, d_n, z_dim=h).to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=5e-4)

if 'model_path' in locals():
    model.load_state_dict(torch.load(model_path, map_location=torch.device(device)))
    print('Saved model loaded.')


train_eval_vae(n, batch_size, epochs, train_set, test_set, model, optimizer)

testsub = torch.tensor(test_set)
truedict = truedicts(all_triples)

lp_results =  link_prediction(model, testsub[:2,:], truedict, batch_size)

outfile_path = 'data/'+dataset+'/lp_results_{}_{}.json'.format(model.name, date.today().strftime("%Y%m%d"))
with open(outfile_path, 'w') as outfile:
    json.dump(lp_results, outfile)
