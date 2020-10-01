# train_x, train_y, model, theta, x, y
from typing import List

import fax
import fax.competitive.extragradient
import fax.constrained
import fax.math
import jax
import jax.experimental.optimizers
import jax.lax
import jax.numpy as np
import jax.ops
import jax.tree_util
import numpy.random as npr
import tqdm

import config
import datasets
from metrics import update_metrics
from network import make_block_net
from utils import ConstrainedParameters, TaskParameters, full_rollout, time_march


def main():
    batch_gen, model, params, train_x, train_y = initialize()

    def full_rollout_loss(theta: List[np.ndarray], batch):
        train_x, batch_train_y, _indices = batch
        pred_y = full_rollout(train_x, model, theta)
        # return np.linalg.norm(pred_y - batch_train_y, 2)
        return -np.mean(np.sum(pred_y * batch_train_y, axis=1))

    def loss_function(params):
        theta, activations = params
        x0 = next(batch_gen)
        _, batch_train_y, indices = x0
        x_n = activations[-1][indices, :]
        # x_n = jax.lax.stop_gradient(x_n)
        # theta = jax.lax.stop_gradient(theta)
        pred_y = full_rollout(x_n, model[-1:], theta[-1:])

        # return np.linalg.norm(pred_y - batch_train_y, 2), x0
        return -np.mean(np.sum(pred_y * batch_train_y, axis=1)), x0

    def equality_constraints(params, task):
        theta, x = params
        task_x, _, task_indices = task
        x = [xi[task_indices, :] for xi in x]

        # Layer 1 -> 2
        h0 = model[0](theta[0], task_x) - jax.lax.stop_gradient(x[0])
        defects = [h0, ]

        # # Layer 2 onward
        # for t in range(len(x) - 1):
        #     block_x = x[t]
        #     block_y = x[t + 1]
        #     block_y_hat = model[t + 1](theta[t + 1], block_x)

        #     defects.append(block_y_hat - block_y)
        return tuple(defects), task_indices

    init_mult, lagrangian, get_x = fax.constrained.make_lagrangian(
        func=loss_function,
        equality_constraints=equality_constraints
    )

    initial_values = init_mult(params, (train_x, train_y, np.arange(train_x.shape[0])))
    optimizer_init, optimizer_update, optimizer_get_params = fax.competitive.extragradient.adam_extragradient_optimizer(
        betas=(config.adam1, config.adam2), step_size=config.lr, weight_norm=config.weight_norm)
    opt_state = optimizer_init(initial_values)

    @jax.jit
    def update(i, opt_state):
        grad_fn = jax.grad(lagrangian, (0, 1))
        return optimizer_update(i, grad_fn, opt_state)

    print("optimize()")

    for iter_num in tqdm.trange(config.num_epochs):
        if iter_num % config.eval_every == 0:
            params = optimizer_get_params(opt_state)
            update_metrics(batch_gen, lagrangian, equality_constraints, full_rollout_loss, loss_function, model, params, iter_num, train_x, train_y)

        opt_state = update(iter_num, opt_state)

    trained_params = optimizer_get_params(opt_state)
    return trained_params


def initialize():
    if config.dataset == "mnist":
        train_x, train_y, _, _ = datasets.mnist()
    elif config.dataset == "iris":
        train_x, train_y, _, _ = datasets.iris()
    else:
        raise ValueError

    dataset_size = train_x.shape[0]
    batch_size = min(config.batch_size, train_x.shape[0])

    def gen_batches() -> (np.ndarray, np.ndarray, List[np.int_]):
        rng = npr.RandomState(0)
        while True:
            indices = np.array(rng.permutation(dataset_size)[:batch_size])  # replace with random.choice
            images = np.array(train_x[indices, :])
            labels = np.array(train_y[indices, :])
            yield TaskParameters(images, labels, indices)

    batches = gen_batches()

    blocks_init, model = make_block_net(num_outputs=train_y.shape[1])
    rng_key = jax.random.PRNGKey(0)
    theta = []
    output_shape = train_x.shape

    for init in blocks_init:
        output_shape, init_params = init(rng_key, output_shape)
        theta.append(init_params)

    y = time_march(train_x, model, theta)
    x = y[:-1]
    params = ConstrainedParameters(theta, x)
    return batches, model, params, train_x, train_y
