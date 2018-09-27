from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import shutil
import sys
import time
import logging
import tensorflow as tf
import fcntl
import src.utils
from src.utils import Logger
from src.cifar10.general_controller import GeneralController
from src.cifar10.micro_controller import MicroController
from src.nni_controller import ENASBaseTuner
from src.cifar10flags import *


def build_logger(log_name):
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_name+'.log')
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    return logger


logger = build_logger("nni_controller_cifar10")


def BuildController(ControllerClass):
    controller_model = ControllerClass(
        search_for=FLAGS.search_for,
        search_whole_channels=FLAGS.controller_search_whole_channels,
        skip_target=FLAGS.controller_skip_target,
        skip_weight=FLAGS.controller_skip_weight,
        num_cells=FLAGS.child_num_cells,
        num_layers=FLAGS.child_num_layers,
        num_branches=FLAGS.child_num_branches,
        out_filters=FLAGS.child_out_filters,
        lstm_size=64,
        lstm_num_layers=1,
        lstm_keep_prob=1.0,
        tanh_constant=FLAGS.controller_tanh_constant,
        op_tanh_reduce=FLAGS.controller_op_tanh_reduce,
        temperature=FLAGS.controller_temperature,
        lr_init=FLAGS.controller_lr,
        lr_dec_start=0,
        lr_dec_every=1000000,  # never decrease learning rate
        l2_reg=FLAGS.controller_l2_reg,
        entropy_weight=FLAGS.controller_entropy_weight,
        bl_dec=FLAGS.controller_bl_dec,
        use_critic=FLAGS.controller_use_critic,
        optim_algo="adam",
        sync_replicas=FLAGS.controller_sync_replicas,
        num_aggregate=FLAGS.controller_num_aggregate,
        num_replicas=FLAGS.controller_num_replicas)

    return controller_model


def get_controller_ops(controller_model):
    """
    Args:
      images: dict with keys {"train", "valid", "test"}.
      labels: dict with keys {"train", "valid", "test"}.
    """

    controller_ops = {
        "train_step": controller_model.train_step,
        "loss": controller_model.loss,
        "train_op": controller_model.train_op,
        "lr": controller_model.lr,
        "grad_norm": controller_model.grad_norm,
        "valid_acc": controller_model.valid_acc,
        "optimizer": controller_model.optimizer,
        "baseline": controller_model.baseline,
        "entropy": controller_model.sample_entropy,
        "sample_arc": controller_model.sample_arc,
        "skip_rate": controller_model.skip_rate,
    }

    return controller_ops


class ENASTuner(ENASBaseTuner):

    def __init__(self, say_hello):

        logger.debug('Parse parameter done.')
        logger.debug(say_hello)

        self.child_totalsteps = (FLAGS.train_data_size + FLAGS.batch_size - 1) // FLAGS.batch_size

        self.controller_total_steps = FLAGS.controller_train_steps * FLAGS.controller_num_aggregate
        logger.debug("child steps:\t"+str(self.child_totalsteps))
        logger.debug("controller step\t"+str(self.controller_total_steps))

        self.epoch = 0

        if FLAGS.search_for == "micro":
            ControllerClass = MicroController
        else:
            ControllerClass = GeneralController
        self.controller_model = BuildController(ControllerClass)


        self.graph = tf.Graph()

        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.1)
        config = tf.ConfigProto(allow_soft_placement=True, gpu_options=gpu_options)

        self.controller_model.build_trainer()
        self.controller_ops = get_controller_ops(self.controller_model)

        hooks = []
        if FLAGS.controller_training and FLAGS.controller_sync_replicas:
            sync_replicas_hook = self.controller_ops["optimizer"].make_session_run_hook(True)
            hooks.append(sync_replicas_hook)

        self.sess = tf.train.SingularMonitoredSession(
            config=config, hooks=hooks, checkpoint_dir=FLAGS.output_dir)
        logger.debug('initlize controller_model done.')

    def generate_parameters(self, parameter_id, trial_job_id=None):
        child_arc = self.get_csvaa(self.controller_total_steps)
        self.epoch = self.epoch + 1
        return child_arc


    def get_csvai(self, child_totalsteps):
        normal_arc = []
        reduce_arc = []
        for _ in range(0, child_totalsteps):
            arc1, arc2 = self.sess.run(self.controller_model.sample_arc)
            normal_arc.append(arc1)
            reduce_arc.append(arc2)
        return normal_arc,reduce_arc


    def controller_one_step(self, epoch, valid_acc_arr):
        logger.debug("Epoch {}: Training controller".format(epoch))

        for ct_step in range(FLAGS.controller_train_steps * FLAGS.controller_num_aggregate):
            run_ops = [
                self.controller_ops["loss"],
                self.controller_ops["entropy"],
                self.controller_ops["lr"],
                self.controller_ops["grad_norm"],
                self.controller_ops["valid_acc"],
                self.controller_ops["baseline"],
                self.controller_ops["skip_rate"],
                self.controller_ops["train_op"],
            ]

            loss, entropy, lr, gn, val_acc, bl, _, _ = self.sess.run(run_ops, feed_dict={
                self.controller_model.valid_acc: valid_acc_arr[ct_step]})

            controller_step = self.sess.run(self.controller_ops["train_step"])

            if ct_step % FLAGS.log_every == 0:

                log_string = ""
                log_string += "ctrl_step={:<6d}".format(controller_step)
                log_string += " loss={:<7.3f}".format(loss)
                log_string += " ent={:<5.2f}".format(entropy)
                log_string += " lr={:<6.4f}".format(lr)
                log_string += " |g|={:<8.4f}".format(gn)
                log_string += " acc={:<6.4f}".format(val_acc)
                log_string += " bl={:<5.2f}".format(bl)
                log_string += " child acc={:<5.2f}".format(valid_acc_arr[ct_step])
                logger.debug(log_string)

        return

    def receive_trial_result(self, parameter_id, parameters, reward, trial_job_id):
        logger.debug("epoch:\t"+str(self.epoch))
        logger.debug(parameter_id)
        logger.debug(reward)
        valid_acc_arr = reward
        self.controller_one_step(self.epoch, valid_acc_arr)
        return


    def update_search_space(self, data):

        pass


    # TODO: nni.send_final_result()
    def send_child_micro_arc(self, epoch, normal_arc, reduce_arc):
        output_path = self.controller_prefix + str(epoch) + ".txt"
        with open(output_path, "w") as out_file:
            fcntl.flock(out_file, fcntl.LOCK_EX)
            number = len(normal_arc)
            out_file.write(str(number) + "\n")

            for i in range(number):
                arc = normal_arc[i]
                self.writearcline(arc, out_file=out_file)
                arc = reduce_arc[i]
                self.writearcline(arc, out_file=out_file)


def main(_):
    logger.debug("-" * 80)

    SearchForMicro = False
    if FLAGS.search_for == "micro":
        SearchForMicro = True

    logger.debug('Parse parameter done!!!!!!!!!!!!!!!!!!!!!!!!.')
    logger.debug("Not here")
    child_totalsteps = (FLAGS.train_data_size + FLAGS.batch_size - 1 )// FLAGS.batch_size

    controler_steps = FLAGS.controller_train_steps * FLAGS.controller_num_aggregate
    say_hello = "hello"
    tuner = ENASTuner(say_hello)
    epoch = 0

    if SearchForMicro:
        while True:
            if epoch >= FLAGS.num_epochs:
                break
            normal_arc,reduce_arc = tuner.get_csvai(controler_steps)
            logger.debug("normal arc length\t" + str(len(normal_arc)))
            # TODO: nni.send_final_result()
            tuner.send_child_micro_arc(epoch, normal_arc, reduce_arc)
            epoch = epoch + 1
            # TODO nni.get_parameters()
            valid_acc_arr = tuner.receive_reward(epoch)

            tuner.controller_one_step(epoch, valid_acc_arr)

    else:
        while True:
            if epoch >= FLAGS.num_epochs:
                break

            # TODO: nni.send_final_result()
            config = tuner.generate_parameters(0)
            epoch = epoch + 1
            # TODO nni.get_parameters()
            valid_acc_arr = tuner.receive_trial_result(0,config,0.99)
            print(valid_acc_arr)
            tuner.controller_one_step(epoch, valid_acc_arr)


if __name__ == "__main__":
    tf.app.run()
