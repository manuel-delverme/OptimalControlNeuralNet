import math
import sys
import torch

import mila_tools

RUN_SWEEP = 1
REMOTE = 1

sweep_yaml = "pytorch/sweep_hyper.yaml" if RUN_SWEEP else False
HOST = "mila" if REMOTE else ""
DEBUG = '_pydev_bundle.pydev_log' in sys.modules.keys()

random_seed = 1337

initial_lr_theta = .001
# initial_lr_x = .05
# initial_lr_y = .08
# high lr_y make the lagrangian more responsive to sign changes -> less oscillation around 0

batch_size = 1024
num_epochs = 150

use_cuda = not DEBUG

################################################################
# END OF PARAMETERS
################################################################
mila_tools.register(locals())
device = torch.device("cuda" if use_cuda else "cpu")

################################################################
# Derivative parameters
################################################################
tb = mila_tools.deploy(host=HOST, sweep_yaml=sweep_yaml, extra_slurm_headers="""
#SBATCH --mem=24GB
""")
