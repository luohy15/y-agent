"""BV/AV number conversion - https://github.com/Prcuvu/bilibili-aid-bvid-converter"""

XOR_CODE = 23442827791579
MASK_CODE = 2251799813685247
BASE = 58
TABLE = 'FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf'
TR = {char: i for i, char in enumerate(TABLE)}


def bv2av(x: str) -> int:
    """Convert BV ID to AV number."""
    if not (x.startswith('BV1') or x.startswith('bv1')):
        raise ValueError('BV id must start with BV1')

    chars = list(x)
    chars[3], chars[9] = chars[9], chars[3]
    chars[4], chars[7] = chars[7], chars[4]

    aid = 0
    for i in range(3, 12):
        aid = aid * BASE + TR[chars[i]]

    return (aid & MASK_CODE) ^ XOR_CODE
