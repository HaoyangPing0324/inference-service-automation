"""Joint candidate: four rows per CTA for medium-width prefill RMSNorm.

Small/decode shapes and fused residual paths retain the installed implementation.
Implicit Hopper PDL optimization is not retained on this experimental branch;
explicit enable_pdl=True is left to the original implementation.
"""
import torch
import triton
import triton.language as tl

_announced = False


@triton.jit
def grouped_rms_kernel(X, W, Y, M: tl.constexpr, N: tl.constexpr,
                       SX: tl.constexpr, SY: tl.constexpr, EPS: tl.constexpr,
                       BLOCK: tl.constexpr, ROWS: tl.constexpr):
    rows = tl.program_id(0) * ROWS + tl.arange(0, ROWS)
    cols = tl.arange(0, BLOCK)
    x = tl.load(X + rows[:, None] * SX + cols[None, :],
                (rows[:, None] < M) & (cols[None, :] < N), other=0).to(tl.float32)
    w = tl.load(W + cols, cols < N, other=0).to(tl.float32)
    inv = tl.rsqrt(tl.sum(x * x, axis=1) / N + EPS)
    y = x * inv[:, None] * w[None, :]
    tl.store(Y + rows[:, None] * SY + cols[None, :], y,
             (rows[:, None] < M) & (cols[None, :] < N))


def rmsnorm(x, weight, eps=1e-6, out=None):
    global _announced
    if out is None:
        out = torch.empty_like(x)
    grouped_rms_kernel[(triton.cdiv(x.shape[0], 4),)](
        x, weight, out, x.shape[0], x.shape[1], x.stride(0), out.stride(0),
        eps, triton.next_power_of_2(x.shape[1]), 4, num_warps=4)
    if not _announced and not torch.cuda.is_current_stream_capturing():
        print(f'JOINT_OPERATOR=grouped-rmsnorm-v1 shape={tuple(x.shape)}', flush=True)
        _announced = True
    return out
