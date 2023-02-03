#!/bin/bash
set -eux

# This script will generate calico and flannel resources needed for canal.
#
# If you want to fetch existing resources from the calico and flannel charms
# in the charm store, see fetch-charm-store-resources.sh in this repository.

ARCH=${ARCH:-"amd64 arm64"}

# 'git' is required
command -v git >/dev/null 2>&1 || { echo 'git: command not found'; exit 1; }

canal_root="${PWD}"
canal_temp="${canal_root}/temp"

test -d "${canal_temp}" && rm -rf "${canal_temp}"
mkdir -p "${canal_temp}"


# FLANNEL RESOURCES:
# The flannel version in the canal and flannel charms are the same; use flannel's
# build-flannel-resource.sh so we build identical resources for the canal charm.
FLANNEL_COMMIT="16d6841f019acc4ff6e5b04059ff4bee6b50057e"
FLANNEL_REPO="https://github.com/charmed-kubernetes/charm-flannel.git"

git clone $FLANNEL_REPO "${canal_temp}/flannel"
pushd ${canal_temp}/flannel
git checkout "$FLANNEL_COMMIT"
ARCH="$ARCH" ./build-flannel-resources.sh
mv flannel-*.gz ${canal_root}
popd


# CALICO RESOURCES:
# The calico version in the canal and calico charms diverged in CK 1.24. Fetch
# and prep specific calico resources for the canal charm.
CALICO_VERSION="v3.10.1"

function fetch_and_validate() {
  # fetch a binary and make sure it's what we expect (executable > 20MB)
  min_bytes=20000000
  location="${1-}"

  # remove everything up until the last slash to get the filename
  filename=$(echo "${location##*/}")
  fetch_cmd="wget ${location} -O ./${filename}"
  ${fetch_cmd}

  # Make sure we fetched something big enough
  actual_bytes=$(wc -c < ${filename})
  if [ $actual_bytes -le $min_bytes ]; then
    echo "$0: ${filename} should be at least ${min_bytes} bytes"
    exit 1
  fi

  # Make sure we fetched a binary
  if ! file ${filename} 2>&1 | grep -q 'executable'; then
    echo "$0: ${filename} is not an executable"
    exit 1
  fi
}

# calico
for arch in ${ARCH}; do
  rm -rf resource-build-$arch
  mkdir resource-build-$arch
  pushd resource-build-$arch
  fetch_and_validate \
    https://github.com/projectcalico/calicoctl/releases/download/$CALICO_VERSION/calicoctl-linux-$arch
  fetch_and_validate \
    https://github.com/projectcalico/cni-plugin/releases/download/$CALICO_VERSION/calico-$arch
  fetch_and_validate \
    https://github.com/projectcalico/cni-plugin/releases/download/$CALICO_VERSION/calico-ipam-$arch

  mv calicoctl-linux-$arch calicoctl
  mv calico-$arch calico
  mv calico-ipam-$arch calico-ipam

  chmod +x calicoctl calico calico-ipam
  tar -zcvf ../calico-$arch.tar.gz .
  popd
  rm -rf resource-build-$arch
done


test -d "${canal_temp}" && rm -rf "${canal_temp}"

touch calico-node-image.tar.gz
