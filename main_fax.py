import collections
import time

import fax.constrained
import fax.constrained.constrained_test
import fax.utils
import jax.experimental.optimizers
import jax.numpy as np
import matplotlib.pyplot as plt
import numpy as onp
import tqdm
from jax import grad, jacrev, jit
from jax.flatten_util import ravel_pytree
from sklearn.preprocessing import normalize

import config

ConstrainedSolution = collections.namedtuple(
    "ConstrainedSolution",
    "value converged iterations"
)

convergence_params = dict(rtol=1e-7, atol=1e-7)


def load_dataset():
    dataset = config.dataset
    import sklearn.model_selection
    targets = dataset.target.reshape(-1)
    n_outputs = len(set(dataset.target))
    one_hot_targets = np.eye(n_outputs)[targets.astype(onp.int)]
    X_train, X_test, y_train, y_test = sklearn.model_selection.train_test_split(dataset.data, one_hot_targets, test_size=0.25, random_state=31337)
    trainX = X_train.astype(np.float32)
    trainY = y_train.astype(np.float32)
    testX = X_test.astype(np.float32)
    testY = y_test.astype(np.float32)
    return n_outputs, trainX, trainY, testX, testY


def drawcurve(train_, valid_, id, legend_1, legend_2):
    acc_train = np.array(train_).flatten()
    acc_test = np.array(valid_).flatten()

    plt.figure(id)
    plt.semilogy(acc_train)
    plt.semilogy(acc_test)
    axes = plt.gca()
    axes.set_ylim([0, 1])

    plt.legend([legend_1, legend_2], loc='upper left')
    plt.show()


def make_BlockNN(num_inputs, num_outputs, dataset_size) -> "BlockNN":
    class FC(collections.namedtuple("FC", "weights bias")):
        def __call__(self, inputs):
            y = np.dot(inputs, self.weights) + self.bias
            return y

    model = [
        [
            FC(onp.random.rand(num_inputs, config.num_hidden), onp.random.rand(1, config.num_hidden)),
            FC(onp.random.rand(num_inputs, config.num_hidden), onp.random.rand(1, config.num_hidden)),
        ],
        [
            FC(onp.random.rand(config.num_hidden, config.num_hidden), onp.random.rand(1, config.num_hidden)),
            FC(onp.random.rand(config.num_hidden, config.num_hidden), onp.random.rand(1, config.num_hidden)),
        ],
        [FC(onp.random.rand(config.num_hidden, num_outputs), onp.random.rand(1, num_outputs))]
    ]
    blocks = []
    split_variables = []
    for i, block in enumerate(model):
        class NNBlock(collections.namedtuple("model", "modules", )):
            def __call__(self, inputs):
                h = inputs
                for module in self.modules:
                    pre_h = module(inputs)
                    h = fax.utils.relu(pre_h)
                y_hat = h
                return y_hat

        nnblock = NNBlock(block)
        blocks.append(nnblock)
        var_out = nnblock.modules[-1].weights.shape[1]
        split_variables.append(onp.random.rand(dataset_size, var_out))

    vars = {
        'blocks': blocks,
        'split_variables': split_variables[:-1],  # the last variable is y_target
    }

    class BlockNN(collections.namedtuple("BlockNN", "blocks split_variables", )):
        def loss(self, inputs, outputs, mini_batch_indices):
            y_hat = self.blocks[-1](self.split_variables[-1][mini_batch_indices])
            return np.linalg.norm(y_hat - outputs, 2) / outputs.shape[0]

        def constraints(self, inputs, samples_indices):
            constraints = []
            splits_left = [inputs, *self.split_variables]

            for a, block, h in zip(splits_left, self.blocks, self.split_variables):
                constraints.append(h - block(a))
            return np.hstack(constraints) / inputs.shape[0]

        def __call__(self, inputs):
            hidden_state = inputs
            for block in self.blocks:
                hidden_state = block(hidden_state)
            y_hat = hidden_state
            return y_hat

    new_cls = BlockNN(*vars.values())
    return new_cls


def run_experiment(num_outputs, trainX, trainY, testX, testY):
    dataset_size, num_inputs = trainX.shape
    batch_size = config.batch_size if config.batch_size > 0 else dataset_size
    model = make_BlockNN(num_inputs, num_outputs, dataset_size)
    indices = np.arange(trainX.shape[0])

    def convergence_test(x_new, x_old):
        return False

    def train_accuracy(*args):
        if len(args) == 1:
            model, = args
        else:
            model, _ = args
        predicted = model(trainX)
        accuracy = np.argmax(trainY, axis=1) == np.argmax(predicted, axis=1)
        return accuracy.mean()

    def objective_function(model):
        if config.batch_size > 0:
            mini_batch_indices = onp.random.choice(indices, config.batch_size, replace=False)
            mini_batch_indices = sorted(mini_batch_indices)
            batchX, batchY = trainX[mini_batch_indices, :], trainY[mini_batch_indices, :]
        else:
            batchX, batchY = trainX, trainY
            mini_batch_indices = indices
        loss = model.loss(batchX, batchY, mini_batch_indices)
        return -loss

    def equality_constraints(model):
        if config.batch_size > 0 and False:
            mini_batch_indices = onp.random.choice(indices, indices.shape[0], replace=False)
            batchX = trainX[mini_batch_indices, :]
        else:
            mini_batch_indices = indices
            batchX = trainX
        return model.constraints(batchX, mini_batch_indices)

    init_mult, lagrangian, get_x = fax.constrained.make_lagrangian(objective_function, equality_constraints)
    initial_values = init_mult(model)

    iters = 1000000
    print('iters', iters)
    lr = jax.experimental.optimizers.inverse_time_decay(5e-3, 5000, 0.3, staircase=True)
    # lr = jax.experimental.optimizers.constant(1e-2)
    start = time.time()
    final_val, h, x, multiplier = fax.constrained.constrained_test.eg_solve(
        lagrangian, convergence_test, equality_constraints, objective_function, get_x, initial_values, max_iter=iters,
        metrics=[
            ("train/objective_function", lambda model, l: objective_function(model).mean()),
            ("train/equality_constraints", lambda model, l: equality_constraints(model).mean()),
            ("train/loss", lagrangian),
            ("train/train_accuracy", train_accuracy)
        ], lr=lr)
    print(train_accuracy(x), time.time() - start)

    return None, None


def plot_learning_curve(train_scores, test_scores):
    _, axes = plt.subplots(1, 1, figsize=(20, 5))
    # axes.set_ylim(0.0, 1)
    axes.set_xlabel("Training examples")
    axes.set_ylabel("Score")

    train_scores_mean = np.mean(train_scores, axis=0)
    train_scores_std = np.std(train_scores, axis=0)
    test_scores_mean = np.mean(test_scores, axis=0)
    test_scores_std = np.std(test_scores, axis=0)
    train_sizes = np.arange(train_scores.shape[1])

    # Plot learning curve
    axes.grid()
    axes.fill_between(train_sizes, train_scores_mean - train_scores_std, train_scores_mean + train_scores_std, alpha=0.1, color="r")
    axes.fill_between(train_sizes, test_scores_mean - test_scores_std, test_scores_mean + test_scores_std, alpha=0.1, color="g")
    axes.plot(train_sizes, train_scores_mean, 'o-', color="r", label="Train")
    axes.plot(train_sizes, test_scores_mean, 'o-', color="g", label="Test")
    axes.legend(loc="best")
    plt.show()


def main():
    num_outputs, trainX, trainY, testX, testY = load_dataset()
    trainX = normalize(trainX, axis=0)
    testX = normalize(testX, axis=0)
    tas, vas = [], []

    # baseline(num_outputs, trainX, trainY)
    for _ in tqdm.trange(1):
        run_experiment(num_outputs, trainX, trainY, testX, testY)
        # tas.append(ta)
        # vas.append(va)

    # drawcurve(list_accuracy_train, list_accuracy_valid, 2, 'acc_train', 'acc_valid')
    plot_learning_curve(np.stack(tas), np.stack(vas))


def baseline(num_outputs, trainX, trainY):
    batch_size, num_inputs = trainX.shape
    model = make_BlockNN(num_inputs, num_outputs, batch_size)
    flat_initial_values, unravel = ravel_pytree(model)

    # def equality_constraints(model):
    #    # mini_batch = np.random.sample(trainX, config.batch_size)

    @jit
    def _objective(variables):
        model = unravel(variables)
        # mini_batch = onp.random.sample(zip(trainX, trainY), config.batch_size)
        loss = model.loss(trainX, trainY)
        return -loss

    @jit
    def _equality_constraints(variables):
        model = unravel(variables)
        outs = model.constraints(trainX)
        return np.ravel(outs)

    @jit
    def gradfun_objective(variables):
        return grad(_objective)(variables)

    @jit
    def jacobian_constraints(variables):
        return jacrev(_equality_constraints)(variables)

    max_iter = 1
    ftol = 1e-6
    options = {'maxiter': max_iter, 'ftol': ftol, 'disp': True}
    constraints = ({'type': 'eq', 'fun': _equality_constraints, 'jac': jacobian_constraints})

    cb = None

    def cb(*x):
        print(x)

    from scipy.optimize import minimize
    start = time.time()
    solution = minimize(_objective, flat_initial_values, method='SLSQP', constraints=constraints, options=options, jac=gradfun_objective, callback=cb)
    print(time.time() - start)

    res = ConstrainedSolution(value=unravel(solution.x), iterations=solution.nit, converged=solution.success)
    model = make_BlockNN(num_inputs, num_outputs, batch_size)

    # init_mult, lagrangian, get_x = fax.constrained.make_lagrangian(objective_function, equality_constraints)
    # initial_values = init_mult(model)
    # cons = ({'type': 'eq', 'fun': model.constraints, },)
    # solution = fax.constrained.slsqp_ecp(model.loss(trainX, trainY), equality_constraints=equality_constraints, initial_values=model)
    scipy_optimal_value = -res.fun
    scipy_constraint = model.constraints(res.x)
    print(f"solution: {res.x} (scipy)")
    print(f"final value: {scipy_optimal_value} (scipy)")
    print(f"constraint: {scipy_constraint} (scipy)")


if __name__ == "__main__":
    main()
