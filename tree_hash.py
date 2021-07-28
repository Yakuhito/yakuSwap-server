"""
This is an implementation of `sha256_treehash`, used to calculate
puzzle hashes in clvm.

This implementation goes to great pains to be non-recursive so we don't
have to worry about blowing out the python stack.
"""

import io

from typing import Optional, Set, Any, BinaryIO

from clvm import CLVMObject

def make_sized_bytes(size: int):
    """
    Create a streamable type that subclasses "bytes" but requires instances
    to be a certain, fixed size.
    """
    name = "bytes%d" % size

    def __new__(cls, v):
        v = bytes(v)
        if not isinstance(v, bytes) or len(v) != size:
            raise ValueError("bad %s initializer %s" % (name, v))
        return bytes.__new__(cls, v)  # type: ignore

    @classmethod  # type: ignore
    def parse(cls, f: BinaryIO) -> Any:
        b = f.read(size)
        assert len(b) == size
        return cls(b)

    def stream(self, f):
        f.write(self)

    @classmethod  # type: ignore
    def from_bytes(cls: Any, blob: bytes) -> Any:
        # pylint: disable=no-member
        f = io.BytesIO(blob)
        result = cls.parse(f)
        assert f.read() == b""
        return result

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self))

    namespace = dict(
        __new__=__new__,
        parse=parse,
        stream=stream,
        from_bytes=from_bytes,
        __bytes__=__bytes__,
        __str__=__str__,
        __repr__=__repr__,
    )

    return type(name, (bytes,), namespace)


bytes32 = make_sized_bytes(32)

def std_hash(b):
    """
    The standard hash used in many places.
    """
    return bytes32(blspy.Util.hash256(bytes(b)))


def sha256_treehash(sexp: CLVMObject, precalculated: Optional[Set[bytes32]] = None) -> bytes32: # sexp:    
    """
    Hash values in `precalculated` are presumed to have been hashed already.
    """

    if precalculated is None:
        precalculated = set()

    def handle_sexp(sexp_stack, op_stack, precalculated: Set[bytes32]) -> None:
        sexp = sexp_stack.pop()
        if sexp.pair:
            p0, p1 = sexp.pair
            sexp_stack.append(p0)
            sexp_stack.append(p1)
            op_stack.append(handle_pair)
            op_stack.append(handle_sexp)
            op_stack.append(roll)
            op_stack.append(handle_sexp)
        else:
            if sexp.atom in precalculated:
                r = sexp.atom
            else:
                r = std_hash(b"\1" + sexp.atom)
            sexp_stack.append(r)

    def handle_pair(sexp_stack, op_stack, precalculated) -> None:
        p0 = sexp_stack.pop()
        p1 = sexp_stack.pop()
        sexp_stack.append(std_hash(b"\2" + p0 + p1))

    def roll(sexp_stack, op_stack, precalculated) -> None:
        p0 = sexp_stack.pop()
        p1 = sexp_stack.pop()
        sexp_stack.append(p0)
        sexp_stack.append(p1)

    sexp_stack = [sexp]
    op_stack = [handle_sexp]
    while len(op_stack) > 0:
        op = op_stack.pop()
        op(sexp_stack, op_stack, precalculated)
    return bytes32(sexp_stack[0])
