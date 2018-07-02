#!/bin/sh
set -eux

rm -rf resource-build
mkdir resource-build
cd resource-build
# Please refer to layer-canal/versioning.md before changing any of these versions.
wget https://github.com/projectcalico/calicoctl/releases/download/v1.6.4/calicoctl
wget https://github.com/projectcalico/cni-plugin/releases/download/v1.11.6/calico
wget https://github.com/projectcalico/cni-plugin/releases/download/v1.11.6/calico-ipam
chmod +x calicoctl calico calico-ipam
tar -vcaf ../calico-resource.tar.gz .
cd ..
rm -rf resource-build
