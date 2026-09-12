"""Controlled fused row-softmax implementation; imported only on a CUDA worker."""
import triton
import triton.language as tl


@triton.jit
def _softmax(source, target, columns: tl.constexpr, BLOCK: tl.constexpr):
    row = tl.program_id(0)
    column = tl.arange(0, BLOCK)
    values = tl.load(source + row * columns + column, column < columns, other=-float("inf"))
    values = values.to(tl.float32)
    numerator = tl.exp(values - tl.max(values, axis=0))
    output = numerator / tl.sum(numerator, axis=0)
    tl.store(target + row * columns + column, output, column < columns)


def softmax(source, *, num_warps: int):
    import torch
    target = torch.empty_like(source)
    _softmax[(source.shape[0],)](source, target, source.shape[1],
        BLOCK=triton.next_power_of_2(source.shape[1]), num_warps=num_warps)
    return target
