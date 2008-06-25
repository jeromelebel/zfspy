"""
ZFSpy: Python bindings for ZFS

Copyright (C) 2008 Chen Zheng <nkchenz@gmail.com>

This file is licensed under the terms of the GNU General Public License
version 2. This program is licensed "as is" without any warranty of any
kind, whether express or implied.
"""
import os
from nvpair import NVPair, StreamUnpacker
from oodict import OODict
from util import *

UBERBLOCK_SHIFT = 10
UBERBLOCK_SIZE = 1 << UBERBLOCK_SHIFT
VDEV_UBERBLOCK_COUNT = 128 << 10 >> UBERBLOCK_SHIFT
SPA_MINBLOCKSHIFT = 9

DMU_OBJTYPE = [
'DMU_OT_NONE',
'DMU_OT_OBJECT_DIRECTORY',
'DMU_OT_OBJECT_ARRAY',
'DMU_OT_PACKED_NVLIST',
'DMU_OT_NVLIST_SIZE',
'DMU_OT_BPLIST',
'DMU_OT_BPLIST_HDR',
'DMU_OT_SPACE_MAP_HEADER',
'DMU_OT_SPACE_MAP',
'DMU_OT_INTENT_LOG',
'DMU_OT_DNODE',
'DMU_OT_OBJSET',
'DMU_OT_DSL_DATASET',
'DMU_OT_DSL_DATASET_CHILD_MAP',
'DMU_OT_OBJSET_SNAP_MAP',
'DMU_OT_DSL_PROPS',
'DMU_OT_DSL_OBJSET',
'DMU_OT_ZNODE',
'DMU_OT_ACL',
'DMU_OT_PLAIN_FILE_CONTENTS',
'DMU_OT_DIRECTORY_CONTENTS',
'DMU_OT_MASTER_NODE',
'DMU_OT_DELETE_QUEUE',
'DMU_OT_ZVOL',
'DMU_OT_ZVOL_PROP',
]

class UberBlock(OODict):
    """ 
    uberblock:  168B
        uint64_t    ub_magic        0x00bab10c
        uint64_t    ub_version             0x1
        uint64_t    ub_txg   
        uint64_t    ub_guid_sum     checksum of all the leaf vdevs's guid
        uint64_t    ub_timestamp    
        blkptr_t    ub_rootbp       point to MOS

    Accordding to lib/libzfscommon/include/sys/vdev_impl.h
        #define VDEV_UBERBLOCK_SHIFT(vd)    \
            MAX((vd)->vdev_top->vdev_ashift, UBERBLOCK_SHIFT)

    minimum allocatable unit for top level vdev is ashift, currently '10' for a RAIDz configuration, 
    '9' otherwise.
    
    lib/libzfscommon/include/sys/uberblock_impl.h 
         #define UBERBLOCK_SHIFT     10          /* up to 1K */
    
    So uberblock elements in array are all aligned to 1K, be carefull! 
    """

    def __init__(self, data):
        if data:
            su = StreamUnpacker(data)
            self.ub_magic, self.ub_version, self.ub_txg, self.ub_guid_sum, self.ub_timestamp = su.repeat('uint64', 5)

    def __repr__(self):
        return '<UberBlock \'ub_txg %s ub_timestamp %s\'>' % (self.ub_txg, self.ub_timestamp)


class BlockPtr(OODict):
    """
    block: 128 b
        3 dvas
        E      1bit   little endian 1, big 0
        level    7bit
        type   1b
        cksum 1b
        comp   1b
        PSIZE  2b  physical size
        LSIZE  2b  logical size
        padding 24b
        birth txg 8b
        fill count 8b
        checksum 32b

    dva:  
        vdev   4b   from lib/libzpool/vdev.c vdev_lookup_top you can see
                    vdev is just the array index of root vdev's children
        grid   1b
        asize  3b
        G      1bit, gang block is a block which contains block pointers
        offset 63bit

    physical block address = offset << 9 + 4M

    You can use BlockPtr() to create a empty block_ptr, please remeber
    to initialize all its members. Always call with initial data is a preferd
    way, zero data for empty block_ptr 
    """


    def __init__(self, data = None):
        if data:
            self.dva = []
            dva_size = 16 
            for dva in split_records(data[0 : dva_size * 3], dva_size):
                self.dva.append(self._parse_dva(dva))
            su = StreamUnpacker(data[dva_size * 3 :])
            i = su.uint64()
            #see lib/libzfscommon/include/sys/spa.h
            self.lsize = (get_bits(i, 0, 16) + 1) << SPA_MINBLOCKSHIFT
            self.psize = (get_bits(i, 16, 16) + 1) << SPA_MINBLOCKSHIFT
            self.comp = get_bits(i, 32, 8)
            self.cksum = get_bits(i, 40, 8)
            self.type = get_bits(i, 48, 8)
            self.level = get_bits(i, 56, 5)
            if get_bits(i, 63, 1):
                self.endian = '<' # little endian
            else:
                self.endian = '>' # big
            self.cksum = ['unknown', 'on', 'off', 'label', 'gang header', 'zilog', 'fletcher2', 'fletcher4', 'SHA-256'][self.cksum]
            self.comp = ['unknown', 'on', 'off', 'lzjb'][self.comp]
            self.type = DMU_OBJTYPE[self.type]
            su.rewind(-24) # skip 24b paddings
            self.birth_txg, self.fill_count = su.repeat('uint64', 2)
            self.checksum = []
            for i in range(4):
                self.checksum.append(su.uint64())

    def _parse_dva(self, data):
        dva = OODict()
        su = StreamUnpacker(data)
        i = su.uint64()
        dva.asize = get_bits(i, 0, 24) << SPA_MINBLOCKSHIFT
        dva.grid = get_bits(i, 24, 8)
        dva.vdev = get_bits(i, 32, 32)
        i = su.uint64()
        dva.offset = get_bits(i, 0, 63) << SPA_MINBLOCKSHIFT
        if get_bits(i, 63, 1):
            dva.G = True
        else:
            dva.G = False
        return dva

    def __repr__(self):
        s = ''
        for i in range(3):
            dva = self.dva[i]
            s = s + '   DVA[%d]=<%s:%x:%x>\n' % (i, dva.vdev, dva.offset, dva.asize)
        s = s + '   %s %s %s birth=%d fill=%d\n' % (self.type, self.cksum, self.comp, self.birth_txg, self.fill_count)
        a = []
        for i in self.checksum:
            a.append('%x' % i)
        s = s + '   chksum=' + ':'.join(a) 
        return '<BlockPtr \n%s>' % s 


class VDevLabel(object):
    """
    VDevLabel
    block device:
        L0 L1 BootBlock.... L2 L3

    sizeof BootBlock = 4M - L0 * 2
    four identical vdev_label L0 L1 L2 L3

    vdev_label:     256K
        blank       8K
        boot header 8K
        xdr nvlist      112K
        uberblock array, 128K  each elements is aligned by 1K

    """

    def __init__(self, data = None):
        self.boot_header = None
        self.nvlist = {}
        self.uberblocks = 0
        self.data = ''
        if data:
            self._from_data(data)

    def _from_data(self, data):
        self.boot_header = data[8 << 10: 16 << 10]
        self.nvlist = NVPair.unpack(data[16 << 10: 128 << 10])
        self.data = NVPair.strip(self.nvlist['value'])
        # find the active uberblock
        ub_array = data[128 << 10 :] 
        ubbest = None
        i = 0
        for data in split_records(ub_array, UBERBLOCK_SIZE):
            ub = UberBlock(data)
            ub.index = i
            i = i + 1
            if ub.ub_magic ==  0x00bab10c or ub.ub_magic ==  0x0cb1ba00:
                if ubbest == None:
                    ubbest = ub
                if ub.ub_txg >= ubbest.ub_txg and ub.ub_timestamp > ubbest.ub_timestamp:
                    ubbest = ub
        data = get_record(ub_array, UBERBLOCK_SIZE, ubbest.index)
        ubbest.ub_rootbp = BlockPtr(data[40: 168])
        self.ubbest = ubbest
         
    def __repr__(self):
        return '<VDevLabel \'txg %s\'>' % self.data.txg 

        
class SPA(object):

    def __init__(self):
        pass


    def vdev_load(self, dev):
        """
        Load vdev label informations, return the four labels

        Return
            [VDevLabel]
        """
        f = open(dev, 'rb')
        l = []
        l.append(VDevLabel(f.read(256 << 10)))
        l.append(VDevLabel(f.read(256 << 10)))
        f.seek(- (512  << 10), os.SEEK_END)
        l.append(VDevLabel(f.read(256 << 10)))
        l.append(VDevLabel(f.read(256 << 10)))
        f.close()
        return l

    def __repr__(self):
        return '<SPA>' 


if __name__ == '__main__':
    from pprint import pprint

    spa = SPA()
    labels = spa.vdev_load('/chenz/disk4')
    for l in labels:
        print l.ubbest
        print l.ubbest.ub_rootbp

    import doctest
    doctest.testmod()