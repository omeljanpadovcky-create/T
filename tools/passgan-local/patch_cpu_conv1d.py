#!/usr/bin/env python
"""Apply idempotent TensorFlow 1.4 / Python 3 compatibility fixes."""
from __future__ import print_function

import os
import re
import sys


def main():
    if len(sys.argv) != 2:
        print("Usage: patch_cpu_conv1d.py /app")
        return 2

    root = sys.argv[1]
    conv_path = os.path.join(root, "tflib", "ops", "conv1d.py")
    sample_path = os.path.join(root, "sample.py")

    if not os.path.isfile(conv_path) or not os.path.isfile(sample_path):
        print("ERROR: expected PassGAN files were not found under: " + root)
        return 2

    with open(conv_path, "r") as handle:
        conv = handle.read()

    # Original upstream code asks TF 1.4 for NCHW Conv1D, which is not
    # implemented on CPU. Convert [batch, channels, width] to NHWC and
    # express the same operation as a 2D convolution with height 1.
    if "data_format='NCHW'" in conv and "tf.nn.conv2d(" not in conv:
        old_conv = re.compile(
            r"(?m)^([ \t]*)result = tf\.nn\.conv1d\(\s*"
            r"value=inputs,\s*filters=filters,\s*stride=stride,\s*"
            r"padding='SAME',\s*data_format='NCHW'\s*\)"
        )
        new_conv = (
            r"\1inputs_nwc = tf.transpose(inputs, [0, 2, 1])\n"
            r"\1inputs_nhwc = tf.expand_dims(inputs_nwc, axis=1)\n"
            r"\1filters_2d = tf.expand_dims(filters, axis=0)\n"
            r"\1result_nhwc = tf.nn.conv2d(\n"
            r"\1    input=inputs_nhwc,\n"
            r"\1    filter=filters_2d,\n"
            r"\1    strides=[1, 1, stride, 1],\n"
            r"\1    padding='SAME',\n"
            r"\1    data_format='NHWC'\n"
            r"\1)\n"
            r"\1result_nwc = tf.squeeze(result_nhwc, axis=1)\n"
            r"\1result = tf.transpose(result_nwc, [0, 2, 1])"
        )
        conv, count = old_conv.subn(new_conv, conv, count=1)
        if count != 1:
            print("ERROR: could not safely locate the original Conv1D block.")
            print("No convolution changes were written.")
            return 3

    # Replace the original NCHW bias workaround with a direct channel reshape.
    old_bias = re.compile(
        r"(?m)^([ \t]*)result = tf\.expand_dims\(result, 3\)\n"
        r"[ \t]*result = tf\.nn\.bias_add\(result, _biases, "
        r"data_format='NCHW'\)\n"
        r"[ \t]*result = tf\.squeeze\(result\)"
    )
    new_bias = r"\1result = result + tf.reshape(_biases, [1, output_dim, 1])"
    if "data_format='NCHW'" in conv:
        conv, count = old_bias.subn(new_bias, conv, count=1)
        if count != 1:
            print("ERROR: could not safely locate the original bias block.")
            print("No convolution changes were written.")
            return 3

    if "data_format='NWC'" in conv:
        print("ERROR: unsupported intermediate NWC patch found; restore upstream conv1d.py and rerun setup.")
        return 4

    with open(conv_path, "w") as handle:
        handle.write(conv)

    with open(sample_path, "r") as handle:
        sample = handle.read()
    sample = sample.replace("pickle.load(f)", "pickle.load(f, encoding='latin1')")
    with open(sample_path, "w") as handle:
        handle.write(sample)

    print("Compatibility patches applied to the isolated PassGAN checkout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
