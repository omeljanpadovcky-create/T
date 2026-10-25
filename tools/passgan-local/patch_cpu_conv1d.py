#!/usr/bin/env python
"""Apply narrow compatibility fixes to a local PassGAN checkout."""
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

    old_conv = re.compile(
        r"(?m)^([ \t]*)result = tf\.nn\.conv1d\(\s*"
        r"value=inputs,\s*filters=filters,\s*stride=stride,\s*"
        r"padding='SAME',\s*data_format='NCHW'\s*\)"
    )
    new_conv = (
        r"\1inputs_nwc = tf.transpose(inputs, [0, 2, 1])\n"
        r"\1result_nwc = tf.nn.conv1d(\n"
        r"\1    value=inputs_nwc,\n"
        r"\1    filters=filters,\n"
        r"\1    stride=stride,\n"
        r"\1    padding='SAME',\n"
        r"\1    data_format='NWC'\n"
        r"\1)\n"
        r"\1result = tf.transpose(result_nwc, [0, 2, 1])"
    )

    if "data_format='NCHW'" in conv:
        conv, count = old_conv.subn(new_conv, conv, count=1)
        if count != 1:
            print("ERROR: could not safely locate the expected Conv1D block.")
            print("No convolution changes were written.")
            return 3

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
            print("ERROR: could not safely locate the expected bias block.")
            print("No convolution changes were written.")
            return 3

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
