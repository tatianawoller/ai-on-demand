from pathlib import Path

import skimage.measure

from em_segment.modules.loading import load_from_yaml
from em_segment.predictions import do_predictions
from utils import save_masks

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--img-path", required=True)
    parser.add_argument("--mask-fname", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model-chkpt", required=True)
    # parser.add_argument(
    #     "--model-type", help="Select model type", default="default"
    # )
    parser.add_argument("--model-config", help="Model parameter config path")

    cli_args = parser.parse_args()

    chkpt_path = Path(cli_args.model_chkpt)
    assert chkpt_path.is_file()
    config_path = Path(cli_args.model_config)
    assert config_path.is_file()

    # Load the trainer/model etc. from yaml config
    trainer, evaluators, config_obj = load_from_yaml(config_path)
    # Run the model on the image
    preds = do_predictions(
        trainer=trainer,
        config=config_obj,
        stack_name=Path(cli_args.img_path).stem,
        stack_filepath=cli_args.img_path,
        chkpt_path=chkpt_path,
        load_kwargs={"map_location": "cpu"}
    )
    labelled_stack = skimage.measure.label(preds > 0.5)
    # Save the stack
    save_masks(
        save_dir=Path(cli_args.output_dir),
        save_name=cli_args.mask_fname,
        masks=labelled_stack,
        stack_slice=False,
        all=True,
        idx=None,
    )
