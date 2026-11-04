import json
import torch
from flashinfer.norm import rmsnorm as baseline
from experiment_rmsnorm import rmsnorm


def main():
    torch.manual_seed(42)
    results = []
    for dtype in (torch.float16, torch.bfloat16):
        for rows in (1, 16, 128):
            for hidden in (128, 512, 1024, 4096, 7168):
                x = torch.randn((rows, hidden), device='cuda', dtype=dtype)
                w = torch.randn(hidden, device='cuda', dtype=dtype)
                actual = rmsnorm(x, w)
                expected = baseline(x, w)
                reference = (x.float() * torch.rsqrt(x.float().square().mean(-1, keepdim=True) + 1e-6) * w.float()).to(dtype)
                atol = 0.03125 if dtype == torch.bfloat16 else 0.004
                torch.testing.assert_close(actual, reference, atol=atol, rtol=0.01)
                torch.testing.assert_close(actual, expected, atol=atol, rtol=0.01)
                out = torch.empty_like(x)
                assert rmsnorm(x, w, out=out).data_ptr() == out.data_ptr()
                torch.testing.assert_close(out, actual, atol=0, rtol=0)
                results.append({'dtype': str(dtype), 'rows': rows, 'hidden': hidden,
                                'max_abs_diff_vs_baseline': (actual.float()-expected.float()).abs().max().item()})
    torch.cuda.synchronize()
    print(json.dumps({'passed': len(results), 'cases': results}, indent=2))


if __name__ == '__main__':
    main()
