# -*- coding: utf-8 -*-
__author__ = 'keven'

import numpy as np
import tensorflow as tf
import utils


class GAN_RNN_GCN_Feature():
    def __init__(self, g_input_step=14, g_input_size=28, g_hidden_size=50, g_output_step=28, g_batch_size=50, g_rate=2e-4,
                 g_epochs=1, d_input_step=28, d_input_size=28, d_hidden_size=50, d_batch_size=50, d_rate=2e-4, d_epochs=1,
                 num_epochs=100, print_interval=10, num_epochs_test=30, attention=0, wgan=0, w_clip=0, num_support=5,
                 gumbel_softmax=0, graph_file="graph.txt", data_file="diffusion.pkl"):
        self.g_input_step = g_input_step
        self.g_input_size = g_input_size
        self.g_hidden_size = g_hidden_size
        self.g_output_step = g_output_step
        self.g_batch_size = g_batch_size
        self.g_rate = g_rate
        self.g_epochs = g_epochs

        self.d_input_step = d_input_step
        self.d_input_size = d_input_size
        self.d_hidden_size = d_hidden_size
        self.d_batch_size = d_batch_size
        self.d_rate = d_rate
        self.d_epochs = d_epochs

        self.num_epochs = num_epochs
        self.print_interval = print_interval
        self.num_epochs_test = num_epochs_test
        self.attention = attention
        self.wgan = wgan
        self.w_clip = w_clip
        self.num_support = num_support
        self.gumbel = gumbel_softmax
        self.graph_file = graph_file
        self.data_file = data_file


    def generator(self, input, input_step, input_size, hidden_size, batch_size, reuse=False):
        with tf.variable_scope("generator") as scope:

            lstm_input = self.graph_conv_network(input, self.lap, input_step, input_size, batch_size, self.num_feature)

            # lstm cell and wrap with dropout
            g_lstm_cell = tf.contrib.rnn.BasicLSTMCell(input_size, forget_bias=0.0, state_is_tuple=True)
            g_lstm_cell_1 = tf.contrib.rnn.BasicLSTMCell(input_size, forget_bias=0.0, state_is_tuple=True)

            g_lstm_cell_attention = tf.contrib.rnn.AttentionCellWrapper(g_lstm_cell, attn_length=10)
            g_lstm_cell_attention_1 = tf.contrib.rnn.AttentionCellWrapper(g_lstm_cell_1, attn_length=10)

            if self.attention == 1:
                g_lstm_cell_drop = tf.contrib.rnn.DropoutWrapper(g_lstm_cell_attention, output_keep_prob=0.9)
                g_lstm_cell_drop_1 = tf.contrib.rnn.DropoutWrapper(g_lstm_cell_attention_1, output_keep_prob=0.9)
            else:
                g_lstm_cell_drop = tf.contrib.rnn.DropoutWrapper(g_lstm_cell, output_keep_prob=0.9)
                g_lstm_cell_drop_1 = tf.contrib.rnn.DropoutWrapper(g_lstm_cell_1, output_keep_prob=0.9)

            g_cell = tf.contrib.rnn.MultiRNNCell([g_lstm_cell_drop, g_lstm_cell_drop_1], state_is_tuple=True)
            g_state_ = g_cell.zero_state(batch_size, tf.float32)
            # g_W_o = utils.glorot([hidden_size, input_size])
            # g_b_o = tf.Variable(tf.random_normal([input_size]))

            # neural network
            g_outputs = []
            g_state = g_state_
            for i in range(input_step):
                if i > 0: tf.get_variable_scope().reuse_variables()
                (g_cell_output, g_state) = g_cell(lstm_input[:, i, :], g_state)  # cell_out: [batch_size, hidden_size]
                g_outputs.append(g_cell_output)  # output: shape[input_step][batch_size, hidden_size]

            # expend outputs to [batch_size, hidden_size * input_step] and then reshape to [batch_size * input_steps, hidden_size]
            g_output = tf.reshape(tf.concat(g_outputs, axis=1), [-1, input_size])
            g_y_soft = tf.nn.softmax(g_output)
            self.z_ = tf.reshape(g_y_soft, [batch_size, input_step, input_size])

            # concentrate input and output of rnn
            x = tf.concat([input, self.z_], axis=1)
            return x

    def graph_conv_network(self, input, lap, input_step, input_size, batch_size, num_feature):
        # W_conv1 = tf.Variable(tf.truncated_normal([self.num_support, num_feature, num_feature], stddev=0.1))
        W_conv1 = utils.glorot([self.num_support, num_feature, num_feature])
        b_conv1 = tf.Variable(tf.constant(0.1, shape=[self.num_support]))

        input_t = tf.transpose(input, perm=[0, 2, 1])
        input_m = tf.reshape(input_t, [batch_size * input_step, input_size])
        # convolve
        supports = []
        for i in range(self.num_support):
            pre = tf.matmul(self.fea, W_conv1[i])
            support_m = tf.matmul(lap[i], pre) + b_conv1[i]
            supports.append(support_m)
        support_sum = tf.add_n(supports)
        h_conv1_temp = tf.matmul(input_m, support_sum)
        h_conv1 = tf.reshape(h_conv1_temp, [batch_size, input_step, num_feature])
        # h_conv1 = tf.nn.relu(output)
        return h_conv1

    def discriminator(self, input, input_step, input_size, hidden_size, output_size, batch_size, reuse=False):
        with tf.variable_scope("discriminator") as scope:
            if reuse:
                scope.reuse_variables()

            gcn_output = self.graph_conv_network(input, self.lap, input_step, input_size, batch_size, self.num_feature)

            # lstm cell and wrap with dropout
            d_lstm_cell = tf.contrib.rnn.BasicLSTMCell(hidden_size, forget_bias=0.0, state_is_tuple=True)
            d_lstm_cell_1 = tf.contrib.rnn.BasicLSTMCell(hidden_size / 2, forget_bias=0.0, state_is_tuple=True)

            d_lstm_cell_attention = tf.contrib.rnn.AttentionCellWrapper(d_lstm_cell, attn_length=10)
            d_lstm_cell_attention_1 = tf.contrib.rnn.AttentionCellWrapper(d_lstm_cell_1, attn_length=10)

            if self.attention == 1:
                d_lstm_cell_drop = tf.contrib.rnn.DropoutWrapper(d_lstm_cell_attention, output_keep_prob=0.9)
                d_lstm_cell_drop_1 = tf.contrib.rnn.DropoutWrapper(d_lstm_cell_attention_1, output_keep_prob=0.9)
            else:
                d_lstm_cell_drop = tf.contrib.rnn.DropoutWrapper(d_lstm_cell, output_keep_prob=0.9)
                d_lstm_cell_drop_1 = tf.contrib.rnn.DropoutWrapper(d_lstm_cell_1, output_keep_prob=0.9)

            d_cell = tf.contrib.rnn.MultiRNNCell([d_lstm_cell_drop, d_lstm_cell_drop_1], state_is_tuple=True)
            d_state_ = d_cell.zero_state(batch_size, tf.float32)

            d_W_o = utils.glorot([input_step * hidden_size / 2, output_size])
            d_b_o = tf.Variable(tf.random_normal([output_size]))

            # neural network
            d_outputs = []
            d_state = d_state_
            for i in range(input_step):
                if i > 0: tf.get_variable_scope().reuse_variables()
                (d_cell_output, d_state) = d_cell(gcn_output[:, i, :], d_state)  # cell_out: [batch_size, hidden_size /2]
                d_outputs.append(d_cell_output)  # output: shape[input_step][batch_size, hidden_size/2]

            # expend outputs to [batch_size, hidden_size/2 * input_step] and then reshape to [batch_size * input_step, hidden_size/2]
            d_output = tf.reshape(tf.concat(d_outputs, axis=1), [batch_size, input_step * hidden_size / 2])
            d_y = tf.matmul(d_output, d_W_o) + d_b_o  # d_y, [batch_size, 1]
            return d_y

    def build_model(self,):
        utils.prepare_data(data_file=self.data_file)
        self.lap_list, self.feature = utils.load_gcn_data(self.graph_file, self.num_support)
        self.num_feature = self.feature.shape[1]
        self.x = tf.placeholder(tf.float32, [None, self.d_input_step, self.d_input_size])
        self.z = tf.placeholder(tf.float32, [None, self.g_input_step, self.g_input_size])
        self.z_t = tf.placeholder(tf.float32, [None, self.g_input_step, self.g_input_size])
        self.lap = tf.placeholder(tf.float32, [self.num_support, self.d_input_size, self.d_input_size])
        self.fea = tf.placeholder(tf.float32, [self.d_input_size, self.num_feature])

        self.x_ = self.generator(self.z, self.g_input_step, self.g_input_size, self.g_hidden_size, self.g_batch_size)
        self.D = self.discriminator(self.x, self.d_input_step, self.d_input_size, self.d_hidden_size, 1, self.g_batch_size)
        self.D_ = self.discriminator(self.x_, self.d_input_step, self.d_input_size, self.d_hidden_size, 1, self.g_batch_size, reuse=True)


        def compute_loss(x, y):
            return tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=x, labels=y))

        def compute_accuracy(x, y):
            # correct_pred = tf.equal(tf.argmax(x, 2), tf.argmax(y, 2))
            # return tf.reduce_mean(tf.cast(correct_pred, tf.float32))
            intersection = tf.sets.set_intersection(tf.argmax(x, 2), tf.argmax(y, 2))
            union = tf.sets.set_union(tf.argmax(x, 2), tf.argmax(y, 2))
            correct_number = tf.reduce_sum(tf.sets.set_size(intersection))
            total_number = tf.reduce_sum(tf.sets.set_size(union))
            # return tf.cast(correct_number, tf.float32) / self.d_input_step / self.d_batch_size
            return tf.cast(correct_number, tf.float32) / tf.cast(total_number, tf.float32)

        if self.wgan == 1:
            self.d_loss_real = tf.reduce_mean(self.D)
            self.d_loss_fake = tf.reduce_mean(self.D_)
            self.g_loss = self.d_loss_fake
            self.d_loss = self.d_loss_real - self.d_loss_fake

        else:
            self.d_loss_real = compute_loss(self.D, tf.ones_like(self.D))
            self.d_loss_fake = compute_loss(self.D_, tf.zeros_like(self.D_))
            self.g_loss = compute_loss(self.D_, tf.ones_like(self.D_))
            self.d_loss = self.d_loss_real + self.d_loss_fake

        self.accuracy = compute_accuracy(self.z_t, self.z_)

    def train(self,):
        self.w_g = [w for w in tf.global_variables() if 'generator' in w.name]
        self.w_d = [w for w in tf.global_variables() if 'discriminator' in w.name]
        d_optim = tf.train.RMSPropOptimizer(self.d_rate).minimize(self.d_loss, var_list=self.w_d)
        g_optim = tf.train.RMSPropOptimizer(self.g_rate).minimize(self.g_loss, var_list=self.w_g)

        clip_updates = [w.assign(tf.clip_by_value(w, -self.w_clip, self.w_clip)) for w in self.w_d]

        init = tf.global_variables_initializer()
        sess = tf.InteractiveSession()
        sess.run(init)

        for i in range(self.num_epochs):
            for j in range(self.d_epochs):
                batch_z, batch_x, batch_z_ = utils.feed_data(self.g_batch_size, self.g_input_step, self.g_input_size)
                feed_dict = {self.z: batch_z, self.x: batch_x, self.z_t: batch_z_, self.lap: self.lap_list, self.fea:self.feature}
                if self.wgan == 1: sess.run(clip_updates, feed_dict=feed_dict)
                sess.run(d_optim, feed_dict)
                g_loss, d_loss, accuracy = sess.run([self.g_loss,self.d_loss,self.accuracy], feed_dict=feed_dict)
                print("Iter %d for D, g_loss = %.5f, d_loss = %.5f, accuracy = %.5f" % (j, g_loss, d_loss, accuracy))

            for j in range(self.g_epochs):
                batch_z, batch_x, batch_z_ = utils.feed_data(self.g_batch_size, self.g_input_step, self.g_input_size)
                feed_dict = {self.z: batch_z, self.x: batch_x, self.z_t: batch_z_, self.lap: self.lap_list, self.fea:self.feature}
                sess.run(g_optim, feed_dict)
                g_loss, d_loss, accuracy = sess.run([self.g_loss,self.d_loss,self.accuracy], feed_dict=feed_dict)
                print("Iter %d for G, g_loss = %.5f, d_loss = %.5f, accuracy = %.5f" % (j, g_loss, d_loss, accuracy))

            if i % self.print_interval == 0:
                batch_z, batch_x, batch_z_ = utils.feed_data(self.g_batch_size, self.g_input_step, self.g_input_size)
                feed_dict = {self.z: batch_z, self.x: batch_x, self.z_t: batch_z_, self.lap: self.lap_list, self.fea:self.feature}
                g_loss, d_loss, accuracy = sess.run([self.g_loss,self.d_loss,self.accuracy], feed_dict=feed_dict)
                print("Iter %d, g_loss = %.5f, d_loss = %.5f, accuracy = %.5f" % (i, g_loss, d_loss, accuracy))

        # test performance
        g_loss_list = d_loss_list = accuracy_list = [0.0] * self.num_epochs_test
        for i in range(self.num_epochs_test):
            batch_z, batch_x, batch_z_ = utils.feed_data(self.g_batch_size, self.g_input_step, self.g_input_size, is_train=False)
            feed_dict = {self.z: batch_z, self.x: batch_x, self.z_t: batch_z_, self.lap: self.lap_list, self.fea:self.feature}
            z_ = sess.run(self.z_,feed_dict=feed_dict)
            g_loss_list[i], d_loss_list[i], accuracy_list[i] = sess.run([self.g_loss, self.d_loss, self.accuracy], feed_dict=feed_dict)
        print("Testing Loss: g_loss = %.5f, d_loss = %.5f, accuracy = %.5f" % (sum(g_loss_list)/len(g_loss_list),
                sum(d_loss_list)/len(d_loss_list) , sum(accuracy_list)/ len(accuracy_list)))



