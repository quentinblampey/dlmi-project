import argparse
import json
import os
from datetime import datetime

import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader

from dataset import LymphDataset, get_transform
from models.aggregators import MeanAggregator, DotAttentionAggregator
from models.back_bone import BackBone
from models.cnn import BaselineCNN, PretrainedCNN
from models.top_head import FullyConnectedHead, LinearHead


def main(args):
    torch.manual_seed(1)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"> Device: {device}\n")

    ### Loaders construction

    files = []
    for dirname, _, filenames in os.walk(args.dataset):
        for filename in filenames:
            files.append(os.path.join(dirname, filename))

    clinical_df = pd.read_csv(os.path.join(args.dataset, "clinical_annotation.csv"), index_col="ID")
    clinical_df['AGE'] = clinical_df['DOB'].apply(lambda dob: 2021 - int(dob[-4:]))
    clinical_df['GENDER'] = clinical_df['GENDER'].apply(lambda gender: 1 if gender == "M" else -1)

    scaler = StandardScaler()
    clinical_df[['LYMPH_COUNT', 'AGE']] = scaler.fit_transform(clinical_df[['LYMPH_COUNT', 'AGE']])

    df_test = clinical_df[clinical_df["LABEL"] == -1]
    df = clinical_df[clinical_df["LABEL"] != -1]

    path_train = [[file for file in files if p_id + '/' in file] for p_id in df.index]
    path_test = [[file for file in files if p_id + '/' in file] for p_id in df_test.index]

    train_dst = LymphDataset(path_train, df, get_transform(True))
    test_dst = LymphDataset(path_test, df_test, get_transform(False))

    train_loader = DataLoader(train_dst, batch_size=1, shuffle=True, num_workers=args.num_workers)
    test_loader = DataLoader(test_dst, batch_size=1, shuffle=False, num_workers=args.num_workers)

    ### CNN
    if args.cnn == 'baseline':
        cnn = BaselineCNN(size=args.size)
    else:
        cnn = PretrainedCNN(size=args.size, cnn=args.cnn)

    ### Aggregator
    if args.aggregator == 'mean':
        aggregator = MeanAggregator()
    elif args.aggregator == 'dot':
        aggregator = DotAttentionAggregator(args.size)
    else:
        raise NameError('Invalid aggregator name')

    ### Top head
    if args.top_head == 'fc':
        top_head = FullyConnectedHead(args.size)
    elif args.top_head == 'linear':
        top_head = LinearHead(args.size)
    else:
        raise NameError('Invalid top_head name')

    ### Training

    model = BackBone(cnn, aggregator, top_head, device).to(device)

    pos_weight = torch.tensor([50 / 113]).to(device)
    loss_fct = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    model.train_only(train_loader, args.epochs, loss_fct, args.learning_rate, args.weight_decay)

    predictions = model.predict(test_loader)
    path_submission = os.path.join(args.submission, f"{datetime.now().strftime('%y-%m-%d_%Hh%Mm%Ss')}.csv")
    print('\npath_submission:', path_submission)
    submission = pd.DataFrame({'ID': test_dst.df.index.values,
                               'Predicted': predictions})
    submission.to_csv(path_submission, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--cnn", type=str, default="baseline", choices=['baseline', 'vgg11', 'vgg16', 'resnet18'],
                        help="cnn name")
    parser.add_argument("-a", "--aggregator", type=str, default="mean",
                        choices=['mean', 'dot'], help="aggregator name")
    parser.add_argument("-t", "--top_head", type=str, default="fc",
                        choices=['fc', 'linear'], help="top head name")
    parser.add_argument("-e", "--epochs", type=int, default=10,
                        help="number of epochs")
    parser.add_argument("-s", "--size", type=int, default=16,
                        help="cnn output size")
    parser.add_argument("-nw", "--num_workers", type=int, default=8,
                        help="number of workers")
    parser.add_argument("-lr", "--learning_rate", type=float, default=1e-4,
                        help="dataset learning rate")
    parser.add_argument("-wd", "--weight_decay", type=float, default=1e-5,
                        help="dataset learning rate")
    parser.add_argument("-ts", "--test_size", type=float, default=0.2,
                        help="dataset learning rate")
    parser.add_argument("-d", "--dataset", type=str, default="../3md3070-dlmi/",
                        help="path to the dataset")
    parser.add_argument("-sub", "--submission",  type=str, default="../submissions", help="path to submission folder")

    args = parser.parse_args()
    print(f"> args:\n{json.dumps(vars(args), sort_keys=True, indent=4)}\n")
    main(args)
