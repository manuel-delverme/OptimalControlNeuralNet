import torch

import tqdm
from torch import nn as nn
from torch.nn import functional as F


class ConstrNetwork(nn.Module):
    def __init__(self, train_loader):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, 1)
        self.conv2 = nn.Conv2d(32, 64, 3, 1)
        # self.dropout1 = nn.Dropout(0.25)
        # self.dropout2 = nn.Dropout(0.5)

        self.fc1 = nn.Linear(9216, 128)
        self.fc2 = nn.Linear(128, 10)

        # raise NotImplementedError("this is too big")
        # self.states = nn.ParameterList([
        #     nn.Parameter(torch.zeros(dataset_size, 9216), requires_grad=True),
        #     nn.Parameter(torch.zeros(dataset_size, 128), requires_grad=True),
        # ])
        dataset_size = len(train_loader.dataset)
        # self.states = nn.ModuleList([
        #     nn.Embedding(dataset_size, 128, _weight=self.block1(train_loader.dataset), sparse=True),
        # ])
        weight = torch.zeros(dataset_size, 128)
        with torch.no_grad():
            for batch_idx, (data, target, indices) in tqdm.tqdm(enumerate(train_loader), total=len(train_loader)):
                x_i = self.block1(data)
                weight[indices] = x_i  # + torch.randn(x_i.shape) * 0.01
        self.x1 = nn.Sequential(
            nn.Embedding(dataset_size, 128, _weight=weight, sparse=True),
            nn.ReLU()
        )
        print("initd")
        # raise NotImplementedError("this is too big")
        # self.multipliers = nn.ParameterList([
        #     nn.Parameter(torch.zeros(dataset_size, 9216), requires_grad=True),
        #     nn.Parameter(torch.zeros(dataset_size, 128), requires_grad=True),
        # ])
        # self.multipliers = nn.ModuleList([nn.Embedding(dataset_size, 128, sparse=True)])

    def step(self, x0, states):
        # x1, x2 = self.states
        x2, = states
        return (
            self.block1(x0),
            # self.block2(x1),
            self.block3(x2)
        )

    def forward(self, x0, indices):
        x1_target = self.x1(indices)

        x1_hat = self.block1(x0)
        x_T = self.block3(x1_target)

        h = x1_hat - x1_target
        # raise config.tb.run.log_tensor_stats(x1_hat)
        # rhs = torch.stack([torch.sum(a * b) for a, b in zip(x_i, multi)])
        return x_T, h

    def full_rollout(self, x):
        x = self.block1(x)
        # x = self.block2(x)
        x = self.block3(x)
        return x

    def block3(self, x):
        x = self.fc2(x)
        output = F.log_softmax(x, dim=1)
        return output

    def block2(self, x):
        x = self.fc1(x)
        x = F.relu(x)
        # x = self.dropout2(x)
        return x

    def block1(self, x):
        x = self.conv1(x)
        x = F.relu(x)
        x = self.conv2(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        # x = self.dropout1(x)
        x = torch.flatten(x, 1)
        x = self.block2(x)
        return x