TARGETS = mountkernfs.sh hostname.sh udev mountdevsubfs.sh hwclock.sh mountall.sh mountall-bootclean.sh mountnfs.sh mountnfs-bootclean.sh checkroot.sh urandom networking checkfs.sh mtab.sh udev-mtab bootmisc.sh uim-sysfs pppd-dns kmod checkroot-bootclean.sh plymouth-log procps
INTERACTIVE = udev checkroot.sh checkfs.sh
udev: mountkernfs.sh
mountdevsubfs.sh: mountkernfs.sh udev
hwclock.sh: mountdevsubfs.sh
mountall.sh: checkfs.sh checkroot-bootclean.sh
mountall-bootclean.sh: mountall.sh
mountnfs.sh: mountall.sh mountall-bootclean.sh networking
mountnfs-bootclean.sh: mountall.sh mountall-bootclean.sh mountnfs.sh
checkroot.sh: hwclock.sh mountdevsubfs.sh hostname.sh
urandom: mountall.sh mountall-bootclean.sh hwclock.sh
networking: mountkernfs.sh mountall.sh mountall-bootclean.sh urandom
checkfs.sh: checkroot.sh mtab.sh
mtab.sh: checkroot.sh
udev-mtab: udev mountall.sh mountall-bootclean.sh
bootmisc.sh: mountall-bootclean.sh mountnfs-bootclean.sh mountall.sh mountnfs.sh udev checkroot-bootclean.sh
uim-sysfs: mountall.sh mountall-bootclean.sh mountnfs.sh mountnfs-bootclean.sh
pppd-dns: mountall.sh mountall-bootclean.sh
kmod: checkroot.sh
checkroot-bootclean.sh: checkroot.sh
plymouth-log: mountall.sh mountall-bootclean.sh mountnfs.sh mountnfs-bootclean.sh
procps: mountkernfs.sh mountall.sh mountall-bootclean.sh udev
