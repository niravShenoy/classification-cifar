#!/usr/bin/env python3

import argparse
import math
import os
import logging
from torch.utils.data import random_split

from dataloader import get_cifar10, get_cifar100
from test import test_cifar10, test_cifar100
from utils import accuracy
from test import test_cifar10, test_cifar100, load_checkpoint, save_checkpoint,  find_model_accuracy

from model.wrn import WideResNet

import torch
import torch.optim as optim
import torch.nn as nn
from torch.utils.data import DataLoader

curr_path = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] - %(message)s',
                    datefmt='%a, %d %b %Y %H:%M:%S', filename=os.path.join(curr_path, 'out.task1.log'))


def main(args):
    if args.dataset == "cifar10":
        args.num_classes = 10
        labeled_dataset, unlabeled_dataset, test_dataset = get_cifar10(args,
                                                                       args.datapath)
    if args.dataset == "cifar100":
        args.num_classes = 100
        labeled_dataset, unlabeled_dataset, test_dataset = get_cifar100(args,
                                                                        args.datapath)
    args.epoch = math.ceil(args.total_iter / args.iter_per_epoch)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    val_size = 1000
    test_size = len(test_dataset) - val_size
    test_dataset, val_dataset = random_split(test_dataset, [test_size, val_size])

    labeled_loader = iter(DataLoader(labeled_dataset,
                                     batch_size=args.train_batch,
                                     shuffle=True,
                                     num_workers=args.num_workers))
    unlabeled_loader = iter(DataLoader(unlabeled_dataset,
                                       batch_size=args.train_batch,
                                       shuffle=True,
                                       num_workers=args.num_workers))
    test_loader = DataLoader(test_dataset,
                             batch_size=args.test_batch,
                             shuffle=False,
                             num_workers=args.num_workers)
                    
    val_loader = DataLoader(val_dataset,
                             batch_size=args.test_batch,
                             shuffle=False,
                             num_workers=args.num_workers)

    model = WideResNet(args.model_depth,
                       args.num_classes, widen_factor=args.model_width, dropRate=0.25)
    model = model.to(device)

    ############################################################################
    # TODO: SUPPLY your code
    ############################################################################

    logging.info('%s; Num Labeled = %s; Epochs = %s; LR = %s; Momentum = %s; wd = %s',
                 args.dataset, args.num_labeled, args.epoch, args.lr, args.momentum, args.wd)

    init_path = os.path.join(curr_path, 'init_model.pt')
    torch.save(model.state_dict(), init_path)

    criterion = nn.CrossEntropyLoss()

    # Code to evaluate the best model

    # path = os.path.join(curr_path,'best_model','cifar10-4000','best_model95.pt')
    # logits = test_cifar10(args, device, test_loader, path)
    # exit()
    # top1, topk = find_model_accuracy(model, test_loader, device)
    # print('top1={}, top5={}'.format(top1, topk))
    # exit()
    

    threshold_list = [0.6, 0.75, 0.95]

    for threshold in threshold_list:
        model.load_state_dict(torch.load(init_path))
        optimizer = optim.SGD(params=model.parameters(), lr=args.lr,
                              momentum=args.momentum, weight_decay=args.wd)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, factor=0.2, patience=7)
        best_loss = float('inf')
        best_path = os.path.join(
            curr_path, 'best_model' + str(int(threshold*100)) + '.pt')
        logging.info('Model Parameters for threshold %s',
                     threshold)
        loss_list = []
        for epoch in range(args.epoch):
            model.train()
            x_pseudo_set = []
            y_pseudo_set = []
            correct = 0
            total = 0
            running_loss = 0.0

            for i in range(args.iter_per_epoch):
                try:
                    # labeled data
                    x_l, y_l = next(labeled_loader)
                except StopIteration:
                    labeled_loader = iter(DataLoader(labeled_dataset,
                                                     batch_size=args.train_batch,
                                                     shuffle=True,
                                                     num_workers=args.num_workers))
                    x_l, y_l = next(labeled_loader)

                try:
                    # unlabeled data
                    x_ul, _ = next(unlabeled_loader)
                except StopIteration:
                    unlabeled_loader = iter(DataLoader(unlabeled_dataset,
                                                       batch_size=args.train_batch,
                                                       shuffle=True,
                                                       num_workers=args.num_workers))
                    x_ul, _ = next(unlabeled_loader)

                x_l, y_l = x_l.to(device), y_l.to(device)
                x_ul = x_ul.to(device)
                ####################################################################
                # TODO: SUPPLY your code
                ####################################################################

                # concatenate labeled and unlabeled
                if x_pseudo_set:
                    x_pseudo_tensor = torch.stack(x_pseudo_set).to(device)
                    x_l = torch.cat((x_l, x_pseudo_tensor))
                    y_l = torch.cat(
                        (y_l, torch.tensor(y_pseudo_set).to(device)))

                # train model
                y_pred_l = model(x_l)

                # compute loss
                correct += (torch.argmax(y_pred_l, axis=1)
                            == y_l).float().sum()
                total += float(x_l.size(dim=0))

                loss = criterion(y_pred_l, y_l)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                running_loss += loss.item()

                # predict unlabeled
                y_pseudo_pred = model(x_ul)

                # add to subset if probability is greater than threshold
                y_pseudo_label_prob, y_pseudo_label_class = torch.max(
                    y_pseudo_pred, axis=1)

                x_pseudo_set = []
                y_pseudo_set = []
                for k, row in enumerate(y_pseudo_label_prob):
                    if row >= threshold:
                        x_pseudo_set.append(x_ul[k, :, :, :])
                        y_pseudo_set.append(y_pseudo_label_class[k])
                # End of batch

            train_accuracy = 100 * correct / total
            running_loss /= args.iter_per_epoch
            loss_list.append(running_loss)

            with torch.no_grad():
                model.eval()
                test_loss = 0.0
                correct = 0.0
                for j, (x_v, y_v) in enumerate(val_loader):
                    x_v, y_v = x_v.to(device), y_v.to(device)
                    y_op_val = model(x_v)
                    loss = criterion(y_op_val, y_v)

                    test_loss += loss.item()
                    _, y_pred_test = y_op_val.max(1)
                    correct += y_pred_test.eq(y_v).sum()

                test_accuracy = 100 * correct.float() / len(val_loader.dataset)
                test_loss = test_loss / j

                logging.info("Epoch %s/%s, Train Accuracy: %.3f, Test Accuracy: %.3f, Training Loss: %.3f, Test Loss: %.3f",
                             epoch+1,
                             args.epoch,
                             train_accuracy.item(),
                             test_accuracy,
                             running_loss,
                             test_loss
                             )

                if test_loss < best_loss:
                    best_loss = test_loss
                    checkpoint = {
                        'epoch': epoch+1,
                        'threshold': threshold,
                        'validation_loss': test_loss,
                        'validation_accuracy': test_accuracy,
                        'state_dict': model.state_dict(),
                    }
                    save_checkpoint(checkpoint, best_path)
            scheduler.step(test_loss)
            print("Epoch {}/{}, Train Accuracy: {:.3f}, Test Accuracy: {:.3f}, Training Loss: {:.3f}, Test Loss: {:.3f}".format(
                epoch+1,
                args.epoch,
                train_accuracy.item(),
                test_accuracy,
                running_loss,
                test_loss
            ))

        logging.info('Training Complete...')

        # Model Evaluation
        logging.info('Evalutating Model for Threshold = %s', threshold)
        if args.dataset == "cifar10":
            test_cifar10(args, device, test_loader, best_path)
        elif args.dataset == "cifar100":
            test_cifar100(args, device, test_loader, best_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pseudo labeling \
                                        of CIFAR10/100 with pytorch")
    parser.add_argument("--dataset", default="cifar10",
                       type=str, choices=["cifar10", "cifar100"])
    # parser.add_argument("--dataset", default="cifar100",
    #                     type=str, choices=["cifar10", "cifar100"])
    parser.add_argument("--datapath", default="./data/",
                        type=str, help="Path to the CIFAR-10/100 dataset")
    # parser.add_argument('--num-labeled', type=int,
    #                     default=2500, help='Total number of labeled samples')
    parser.add_argument('--num-labeled', type=int,
                        default=4000, help='Total number of labeled samples')
    parser.add_argument("--lr", default=0.1, type=float,
                        help="The initial learning rate")
    # parser.add_argument("--lr", default=0.01, type=float,
    #                     help="The initial learning rate")
    parser.add_argument("--momentum", default=0.9, type=float,
                        help="Optimizer momentum")
    parser.add_argument("--wd", default=0.0005, type=float,
                        help="Weight decay")
#   parser.add_argument("--wd", default=0.0001, type=float,
#                       help="Weight decay")
    parser.add_argument("--expand-labels", action="store_true",
                        help="expand labels to fit eval steps")
    parser.add_argument('--train-batch', default=64, type=int,
                        help='train batchsize')
    parser.add_argument('--test-batch', default=64, type=int,
                        help='train batchsize')
    parser.add_argument('--total-iter', default=1024*100, type=int,
                        help='total number of iterations to run')
    parser.add_argument('--iter-per-epoch', default=1024, type=int,
                        help="Number of iterations to run per epoch")
    parser.add_argument('--num-workers', default=1, type=int,
                        help="Number of workers to launch during training")
    parser.add_argument('--threshold', type=float, default=0.95,
                        help='Confidence Threshold for pseudo labeling')
    parser.add_argument("--dataout", type=str, default="./path/to/output/",
                        help="Path to save log files")
    parser.add_argument("--model-depth", type=int, default=16,
                        help="model depth for wide resnet")
    parser.add_argument("--model-width", type=int, default=8,
                        help="model width for wide resnet")

    # Add more arguments if you need them
    # Describe them in help
    # You can (and should) change the default values of the arguments

    args = parser.parse_args()

    main(args)
