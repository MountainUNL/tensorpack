#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: celebA.py
# Author: Yuxin Wu <ppwwyyxxc@gmail.com>

import numpy as np
import tensorflow as tf
import glob
import os, sys
import argparse
import cv2

from tensorpack import *
from tensorpack.utils.viz import build_patch_list
from tensorpack.utils.viz import dump_dataflow_images
from tensorpack.tfutils.summary import add_moving_summary, summary_moving_average
import tensorpack.tfutils.symbolic_functions as symbf
from GAN import GANTrainer, RandomZData, build_GAN_losses

"""
DCGAN on CelebA dataset.
1. Download the 'aligned&cropped' version of CelebA dataset.
2. Start training:
    ./celebA.py --data /path/to/image_align_celeba/
3. Visualize samples of a trained model:
    ./celebA.py --load model.tfmodel --sample
"""

SHAPE = 64
BATCH = 128

class Model(ModelDesc):
    def _get_input_vars(self):
        return [InputVar(tf.float32, (None, SHAPE, SHAPE, 3), 'input') ]

    def generator(self, z):
        """ return a image generated from z"""
        l = FullyConnected('fc0', z, 64 * 8 * 4 * 4, nl=tf.identity)
        l = tf.reshape(l, [-1, 4, 4, 64*8])
        l = BNReLU(l)
        with argscope(Deconv2D, nl=BNReLU, kernel_shape=5, stride=2):
            l = Deconv2D('deconv1', l, [8, 8, 64 * 4])
            l = Deconv2D('deconv2', l, [16, 16, 64 * 2])
            l = Deconv2D('deconv3', l, [32, 32, 64])
            l = Deconv2D('deconv4', l, [64, 64, 3], nl=tf.identity)
            l = tf.tanh(l, name='gen')
        return l

    def discriminator(self, imgs):
        """ return a (b, 1) logits"""
        with argscope(Conv2D, nl=tf.identity, kernel_shape=5, stride=2), \
                argscope(LeakyReLU, alpha=0.2):
            l = (LinearWrap(imgs)
                .Conv2D('conv0', 64)
                .LeakyReLU('lr0')
                .Conv2D('conv1', 64*2)
                .BatchNorm('bn1')
                .LeakyReLU('lr1')
                .Conv2D('conv2', 64*4)
                .BatchNorm('bn2')
                .LeakyReLU('lr2')
                .Conv2D('conv3', 64*8)
                .BatchNorm('bn3')
                .LeakyReLU('lr3')
                .FullyConnected('fct', 1, nl=tf.identity)())
        return l

    def _build_graph(self, input_vars):
        image_pos = input_vars[0]
        image_pos = image_pos / 128.0 - 1
        z = tf.random_uniform(tf.pack([tf.shape(image_pos)[0], 100]), -1, 1, name='z')
        z.set_shape([None, 100])    # issue#5680

        with argscope([Conv2D, Deconv2D, FullyConnected],
                W_init=tf.truncated_normal_initializer(stddev=0.02)):
            with tf.variable_scope('gen'):
                image_gen = self.generator(z)
                tf.image_summary('gen', image_gen, max_images=30)
            with tf.variable_scope('discrim'):
                vecpos = self.discriminator(image_pos)
            with tf.variable_scope('discrim', reuse=True):
                vecneg = self.discriminator(image_gen)

        self.g_loss, self.d_loss = build_GAN_losses(vecpos, vecneg)
        all_vars = tf.trainable_variables()
        self.g_vars = [v for v in all_vars if v.name.startswith('gen/')]
        self.d_vars = [v for v in all_vars if v.name.startswith('discrim/')]

def get_data():
    datadir = args.data
    imgs = glob.glob(datadir + '/*.jpg')
    ds = ImageFromFile(imgs, channel=3, shuffle=True)
    augs = [ imgaug.CenterCrop(110), imgaug.Resize(64) ]
    ds = AugmentImageComponent(ds, augs)
    ds = BatchData(ds, BATCH)
    ds = PrefetchDataZMQ(ds, 1)
    return ds

def get_config():
    logger.auto_set_dir()
    dataset = get_data()
    lr = symbolic_functions.get_scalar_var('learning_rate', 2e-4, summary=True)
    return TrainConfig(
        dataset=dataset,
        optimizer=tf.train.AdamOptimizer(lr, beta1=0.5, epsilon=1e-3),
        callbacks=Callbacks([
            StatPrinter(), ModelSaver(),
            ScheduledHyperParamSetter('learning_rate', [(200, 1e-4)])
        ]),
        session_config=get_default_sess_config(0.5),
        model=Model(),
        step_per_epoch=300,
        max_epoch=500,
    )

def sample(model_path):
    pred = PredictConfig(
       session_init=get_model_loader(model_path),
       model=Model(),
       input_names=['z'],
       output_names=['gen/gen'])
    pred = SimpleDatasetPredictor(pred, RandomZData((128, 100)))
    for o in pred.get_result():
        o = o[0] + 1
        o = o * 128.0
        o = o[:,:,:,::-1]
        viz = next(build_patch_list(o, nr_row=10, nr_col=10))
        cv2.imshow("", viz)
        cv2.waitKey()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--gpu', help='comma separated list of GPU(s) to use.')
    parser.add_argument('--load', help='load model')
    parser.add_argument('--sample', action='store_true', help='run sampling')
    parser.add_argument('--data', help='`image_align_celeba` directory of the celebA dataset')
    global args
    args = parser.parse_args()
    if args.gpu:
        os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu
    if args.sample:
        sample(args.load)
    else:
        config = get_config()
        if args.load:
            config.session_init = SaverRestore(args.load)
        GANTrainer(config).train()

