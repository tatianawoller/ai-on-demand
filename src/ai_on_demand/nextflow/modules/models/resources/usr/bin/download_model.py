import argparse
from pathlib import Path
import shutil
from typing import Union

import requests
from tqdm.auto import tqdm

# SAM_MODELS = {
#     "everything": {
#         "default": {
#             "filename": "sam_default.pth",
#             "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
#         },
#         "vit_h": {
#             "filename": "sam_vit_h.pth",
#             "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
#         },
#         "vit_l": {
#             "filename": "sam_vit_l.pth",
#             "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth",
#         },
#         "vit_b": {
#             "filename": "sam_vit_b.pth",
#             "url": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth",
#         },
#         "MedSAM": {
#             "filename": "sam_MedSAM.pth",
#             "url": "https://syncandshare.desy.de/index.php/s/yLfdFbpfEGSHJWY/download/medsam_20230423_vit_b_0.0.1.pth",
#         },
#     }
# }

# UNET_MODELS = {
#     "mito": {
#         "Attention U-Net": {
#             "filename": "Attention_HUNet_3e5_Adam_restart_12_16.best.1266.pt",
#             "dir": "/nemo/stp/ddt/working/shandc/aiod_models/"
#         },
#     },
#     "ne": {
#         "Attention U-Net": {
#             "filename": "Attention_HUNet_NE.best.368.pt",
#             "dir": "/nemo/stp/ddt/working/shandc/aiod_models/"
#         }
#     }
# }

# MODEL_BANK = {"sam": SAM_MODELS, "unet": UNET_MODELS}


def get_model_checkpoint(
    chkpt_dir: Union[Path, str], chkpt_fname: str, chkpt_loc: str, chkpt_type: str, 
):
    # Get the model dict
    # model_dict = MODEL_BANK[model_name][task]
    # Get the checkpoint filename
    # chkpt_fname = Path(model_dict[model_type]["filename"])
    # Just return if this already exists
    # NOTE: Using chkpt_dir here as that's where Nextflow will copy the result to
    if (Path(chkpt_dir) / chkpt_fname).exists():
        return
    # Check whether we are using a local path or a URL
    if chkpt_type == "url":
        print(f"Downloading {chkpt_loc}")
        download_from_url(chkpt_loc, Path(chkpt_fname))
    elif chkpt_type == "dir":
        print(f"Copying {chkpt_loc}")
        copy_from_path(chkpt_loc, Path(chkpt_fname))
    else:
        raise KeyError(
            f"Either 'url' or 'dir' must be specified!"
        )


def download_from_url(url: str, chkpt_fname: Union[Path, str]):
    # Open the URL and get the content length
    req = requests.get(url, stream=True)
    req.raise_for_status()
    content_length = int(req.headers.get("Content-Length"))

    # Download the file and update the progress bar
    with open(chkpt_fname, "wb") as f:
        with tqdm(
            desc=f"Downloading {chkpt_fname.name}...",
            total=content_length,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as pbar:
            for chunk in req.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))
    # Close request
    req.close()
    print(f"Done! Checkpoint saved to {chkpt_fname}")


def copy_from_path(fpath: Union[Path, str], chkpt_fname: Union[Path, str]):
    if not Path(fpath).is_file():
        raise FileNotFoundError(f"Model checkpoint not found: {fpath}")
    # Copy the file from accessible path
    shutil.copy(fpath, chkpt_fname)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chkpt-path",
        required=True,
        type=str,
        help="Full path to model checkpoint",
    )
    parser.add_argument(
        "--chkpt-loc",
        required=True,
        type=str,
        help="Location of model checkpoint",
    )
    parser.add_argument(
        "--chkpt-type",
        required=True,
        type=str,
        help="Type of model checkpoint location",
    )

    args = parser.parse_args()

    chkpt_dir = Path(args.chkpt_path).parent
    chkpt_fname = Path(args.chkpt_path).name

    get_model_checkpoint(
        chkpt_dir=chkpt_dir,
        chkpt_fname=chkpt_fname,
        chkpt_loc=args.chkpt_loc,
        chkpt_type=args.chkpt_type,
    )
