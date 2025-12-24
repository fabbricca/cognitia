#!/usr/bin/env python3
"""
RVC FP32 Wrapper - Forces FP32 mode for GPUs that don't support FP16 well.

This patches the rvc-python library at runtime to force FP32 mode,
which fixes "batch_norm not implemented for 'Half'" errors.
"""

import sys
import os

# ============================================================================
# PATCH 1: Override torch.Tensor.half() to return float() instead
# This ensures no tensors are converted to half precision
# ============================================================================

import torch

_original_half = torch.Tensor.half

def _force_float(self, *args, **kwargs):
    """Override .half() to return .float() instead"""
    return self.float()

# Apply the patch
torch.Tensor.half = _force_float

print("[FP32 Wrapper] Patched torch.Tensor.half() to return float()")

# ============================================================================
# PATCH 2: Override torch.nn.Module.half() as well
# ============================================================================

_original_module_half = torch.nn.Module.half

def _force_module_float(self, *args, **kwargs):
    """Override Module.half() to return Module.float() instead"""
    return self.float()

torch.nn.Module.half = _force_module_float

print("[FP32 Wrapper] Patched torch.nn.Module.half() to return float()")

# ============================================================================
# PATCH 3: Patch the Config class singleton before it gets created
# ============================================================================

def patch_rvc_config():
    """Patch the RVC Config class to force is_half=False"""
    try:
        from rvc_python.configs.config import Config
        
        # Store original __init__
        _original_init = Config.__init__
        
        def patched_init(self, lib_dir, device, is_dml=False):
            # Call original init
            _original_init(self, lib_dir, device, is_dml)
            # Force FP32 mode
            self.is_half = False
            print(f"[FP32 Wrapper] Forced is_half=False for device {device}")
        
        Config.__init__ = patched_init
        print("[FP32 Wrapper] Patched RVC Config class")
        
    except Exception as e:
        print(f"[FP32 Wrapper] Warning: Could not patch Config: {e}")

patch_rvc_config()

# ============================================================================
# PATCH 4: Patch inference pipeline to ensure it uses float32
# ============================================================================

def patch_pipeline():
    """Patch the voice conversion pipeline"""
    try:
        # Patch the VC pipeline
        import rvc_python.modules.vc.pipeline as pipeline_module
        
        if hasattr(pipeline_module, 'VC'):
            original_vc_init = pipeline_module.VC.__init__
            
            def patched_vc_init(self, *args, **kwargs):
                original_vc_init(self, *args, **kwargs)
                # Ensure the model is in float mode
                if hasattr(self, 'net_g') and self.net_g is not None:
                    self.net_g = self.net_g.float()
                if hasattr(self, 'hubert_model') and self.hubert_model is not None:
                    self.hubert_model = self.hubert_model.float()
                    
            pipeline_module.VC.__init__ = patched_vc_init
            print("[FP32 Wrapper] Patched VC pipeline class")
            
    except Exception as e:
        print(f"[FP32 Wrapper] Warning: Could not patch pipeline: {e}")

patch_pipeline()

# ============================================================================
# PATCH 5: Environment variable to disable CUDA FP16
# ============================================================================

os.environ['PYTORCH_NO_CUDA_HALF'] = '1'
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'  # Better error messages

print("[FP32 Wrapper] Environment variables set")

# ============================================================================
# Now run the RVC CLI with the patched modules
# ============================================================================

if __name__ == "__main__":
    print("[FP32 Wrapper] Starting RVC with FP32 mode enforced...")
    print(f"[FP32 Wrapper] Arguments: {sys.argv[1:]}")
    
    # Import and run the RVC CLI from __main__
    from rvc_python.__main__ import main
    
    # Remove 'rvc_fp32_wrapper.py' from args and pass the rest to RVC CLI
    sys.argv = ['rvc'] + sys.argv[1:]
    
    try:
        main()
    except Exception as e:
        print(f"[FP32 Wrapper] Error running RVC: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
