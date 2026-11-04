"""Experimental GPU RMSNorm implementation, not a performance claim.

One Triton program per row; FP32 reduction and product, output in input dtype.
Only the standard unfused RMSNorm path is replaced. Fused residual paths remain
the installed baseline. This module is loaded only by the operator variant.
"""
import torch
import triton
import triton.language as tl

_announced = False


@triton.jit
def experimental_rmsnorm_kernel(X, W, Y, SX: tl.constexpr, SY: tl.constexpr,
                               N: tl.constexpr, EPS: tl.constexpr,
                               BLOCK: tl.constexpr):
    row = tl.program_id(0)
    col = tl.arange(0, BLOCK)
    x = tl.load(X + row * SX + col, col < N, other=0).to(tl.float32)
    w = tl.load(W + col, col < N, other=0).to(tl.float32)
    inv_rms = tl.rsqrt(tl.sum(x * x, axis=0) / N + EPS)
    tl.store(Y + row * SY + col, x * inv_rms * w, col < N)


def rmsnorm(input, weight, eps=1e-6, out=None, enable_pdl=None):
    global _announced
    if input.ndim != 2 or input.stride(-1) != 1 or weight.ndim != 1:
        raise ValueError('Experimental RMSNorm requires 2D input and contiguous columns')
    if input.shape[1] != weight.numel() or not weight.is_contiguous():
        raise ValueError('Experimental RMSNorm weight shape/stride mismatch')
    if not input.is_cuda or input.dtype not in (torch.float16, torch.bfloat16):
        raise ValueError('Experimental RMSNorm supports CUDA FP16/BF16 only')
    if out is None:
        out = torch.empty_like(input)
    if out.shape != input.shape or out.stride(-1) != 1 or out.dtype != input.dtype:
        raise ValueError('Experimental RMSNorm output shape/stride/dtype mismatch')
    if input.shape[0]:
        block = triton.next_power_of_2(input.shape[1])
        experimental_rmsnorm_kernel[(input.shape[0],)](
            input, weight, out, input.stride(0), out.stride(0), input.shape[1],
            eps, block, num_warps=4 if block <= 2048 else 8)
        if not _announced:
            print(f'OPERATOR_VARIANT=triton-rmsnorm-v1 shape={tuple(input.shape)} dtype={input.dtype}', flush=True)
            _announced = True
    return out
