
def get_bits(i, start, len):
    """
    Get part of a integer i, from bits start, length is len

    """
    return (i >> start) & ((1 << len) - 1)

def hexprint(data):
    """
    data will be aligned to 8 bytes first, then print out with line numbers
    hex values, and accsii chars

    """
    from binascii import hexlify
    #padding
    mod = len(data) % 8
    if mod != 0:
        for i in range(8 - mod):
            data = data + '\x00'
    ln = len(data) / 8
    for n in range(ln):
        line = data[n * 8: (n + 1) * 8]
        hd = hexlify(line).upper()
        print '%4x' % n, hd[:8], hd[8:], '   ',
        for c in line:
            if c.isalpha():
                print c,
        print

if __name__ == '__main__':
    a = get_bits(0x62c3a, 0, 63)
    print '%x' % (a << 9)
