
"""
docstring
"""
import sys
import os
import random
import argparse
from util import resampling_idxes, load_raw_data
from mol_lib import MOLLIB
import numpy as np
from tqdm import tqdm
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
sys.path.append('%s/../s2v_lib' % os.path.dirname(os.path.realpath(__file__)))
from embedding import EmbedMeanField, EmbedLoopyBP
from mlp import MLPRegression


def main(args):
    """
    doctstring
    """
    raw_data_dict = load_raw_data()

    regressor = Regressor(args.gm, args.latent_dim, args.out_dim,
                          args.max_lv, args.hidden, mode)
    if args.mode == 'gpu':
        regressor = regressor.cuda()
    if args.saved_model is not None and args.saved_model != '':
        if os.path.isfile(args.saved_model):
            print('loading model from %s' % args.saved_model)
            if args.mode == 'cpu':
                regressor.load_state_dict(torch.load(args.saved_model,
                                                     map_location=lambda storage, loc: storage))
            else:
                regressor.load_state_dict(torch.load(args.saved_model))

    if args.phase == 'test':
        test_data = MOLLIB.LoadMolGraph('test', raw_data_dict['test'])
        test_loss = loop_dataset(test_data, regressor, list(range(len(test_data))))
        print('\033[93maverage test loss: mae %.5f rmse %.5f\033[0m' % (test_loss[0], test_loss[1]))
        sys.exit()

    train_idxes = resampling_idxes(raw_data_dict)
    cooked_data_dict = {}

    for d in raw_data_dict:
        cooked_data_dict[d] = MOLLIB.LoadMolGraph(d, raw_data_dict[d])

    optimizer = optim.Adam(regressor.parameters(), lr=args.learning_rate)
    iter_train = (len(train_idxes) + (args.batch_size - 1)) // args.batch_size

    best_valid_loss = None
    for epoch in range(args.num_epochs):
        valid_interval = 10000
        for i in range(0, iter_train, valid_interval):
            avg_loss = loop_dataset(cooked_data_dict['train'],
                                    regressor,
                                    train_idxes,
                                    optimizer,
                                    start_iter=i,
                                    n_iters=valid_interval)
            print('\033[92maverage training of epoch %.2f: mae %.5f rmse %.5f\033[0m'
                  % (epoch + min(float(i + valid_interval) / iter_train, 1.0),
                     avg_loss[0], avg_loss[1]))

            valid_loss = loop_dataset(cooked_data_dict['valid'],
                                      regressor,
                                      list(range(len(cooked_data_dict['valid']))))
            print('\033[93maverage valid of epoch %.2f: mae %.5f rmse %.5f\033[0m'
                  % (epoch + min(float(i + valid_interval) / iter_train, 1.0),
                     valid_loss[0], valid_loss[1]))
 
            if best_valid_loss is None or valid_loss[0] < best_valid_loss:
                best_valid_loss = valid_loss[0]
                print('----saving to best model since this is the best valid loss so far.----')
                torch.save(regressor.state_dict(), args.save_dir + '/epoch-best.model')

        random.shuffle(train_idxes)


def loop_dataset(mol_list, regressor, sample_idxes, optimizer=None,
                 start_iter=None, n_iters=None, bsize=cmd_args.batch_size):
    """
    doctstring
    """
    total_loss = []
    total_iters = (len(sample_idxes) + (bsize - 1) * (optimizer is None)) // bsize
    if start_iter is not None:
        ed_iter = start_iter + n_iters
        if ed_iter > total_iters:
            ed_iter = total_iters
        pbar = tqdm(range(start_iter, ed_iter), unit='batch')
    else:
        pbar = tqdm(range(total_iters), unit='batch')

    n_samples = 0
    for pos in pbar:
        selected_idx = sample_idxes[pos * bsize : (pos + 1) * bsize]

        batch_graph = [mol_list[idx] for idx in selected_idx]
        _, mae, mse = regressor(batch_graph)

        if optimizer is not None:
            optimizer.zero_grad()
            mse.backward()
            optimizer.step()

        mae = mae.data.cpu().numpy()[0]
        mse = mse.data.cpu().numpy()[0]
        pbar.set_description('mae: %0.5f rmse: %0.5f' % (mae, np.sqrt(mse)))

        total_loss.append(np.array([mae, mse]) * len(selected_idx))

        n_samples += len(selected_idx)
    if optimizer is None:
        assert n_samples == len(sample_idxes)
    total_loss = np.array(total_loss)
    avg_loss = np.sum(total_loss, 0) / n_samples
    avg_loss[1] = np.sqrt(avg_loss[1])
    return avg_loss


class Regressor(nn.Module, gm, latent_dim, out_dim, max_lv, hidden, mode):
    """
    doctstring
    """
    def __init__(self):
        super(Regressor, self).__init__()
        if gm == 'mean_field':
            model = EmbedMeanField
        elif gm == 'loopy_bp':
            model = EmbedLoopyBP
        else:
            print('unknown gm %s' % gm)
            sys.exit()

        self.s2v = model(latent_dim=latent_dim,
                         output_dim=out_dim,
                         num_node_feats=MOLLIB.num_node_feats,
                         num_edge_feats=MOLLIB.num_edge_feats,
                         max_lv=max_lv)
        self.mlp = MLPRegression(input_size=out_dim, hidden_size=hidden)

    def forward(self, batch_graph): 
        node_feat, edge_feat, labels = MOLLIB.PrepareFeatureLabel(batch_graph)
        if mode == 'gpu':
            node_feat = node_feat.cuda()
            edge_feat = edge_feat.cuda()
            labels = labels.cuda()
        embed = self.s2v(batch_graph, node_feat, edge_feat)

        return self.mlp(embed, labels)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Argparser for harvard cep')
    parser.add_argument('-saved_model', default=None, help='start from existing model')
    parser.add_argument('-save_dir', default='./saved', help='save_dir')
    parser.add_argument('-mode', default='gpu', help='cpu/gpu')
    parser.add_argument('-gm', default='mean_field', help='mean_field/loopy_bp')
    parser.add_argument('-phase', default='train', help='train/test')
    parser.add_argument('-batch_size', type=int, default=50, help='minibatch size')
    parser.add_argument('-seed', type=int, default=1, help='seed')
    parser.add_argument('-gen_depth', type=int, default=10, help='depth of generator')
    parser.add_argument('-num_epochs', type=int, default=1000, help='number of epochs')
    parser.add_argument('-latent_dim', type=int, default=64, help='dimension of latent layers')
    parser.add_argument('-out_dim', type=int, default=1024, help='s2v output size')
    parser.add_argument('-hidden', type=int, default=100, help='dimension of regression')
    parser.add_argument('-max_lv', type=int, default=4, help='max rounds of message passing')
    parser.add_argument('-learning_rate', type=float, default=0.0001, help='init learning_rate')

    cmd_args, _ = parser.parse_known_args()

    random.seed(cmd_args.seed)
    np.random.seed(cmd_args.seed)
    torch.manual_seed(cmd_args.seed)
    main(cmd_args)
