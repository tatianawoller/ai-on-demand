from collections import defaultdict
from pathlib import Path
import subprocess
from typing import Optional

import napari
from napari.qt.threading import thread_worker
from napari.utils.notifications import show_info
import numpy as np
import pandas as pd
from qtpy.QtWidgets import (
    QWidget,
    QLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QFileDialog,
    QProgressBar,
    QCheckBox,
)
import tqdm
from ai_on_demand.models import MODEL_TASK_VERSIONS
from ai_on_demand.tasks import TASK_NAMES
from ai_on_demand.utils import sanitise_name, format_tooltip
from ai_on_demand.widget_classes import SubWidget


class NxfWidget(SubWidget):
    _name = "nxf"

    def __init__(
        self,
        viewer: napari.Viewer,
        pipeline: str,
        parent: Optional[QWidget] = None,
        layout: QLayout = QGridLayout,
    ):
        super().__init__(
            viewer=viewer,
            title="Execution",
            parent=parent,
            layout=layout,
            tooltip="""
Allows for the computational pipeline to be triggered, with different additional options depending on the main widget selected.
The profile determines where the pipeline is run.
""",
        )

        # Define attributes that may be useful outside of this class
        # or throughout it
        self.nxf_repo = "FrancisCrickInstitute/Segment-Flow"
        # Set the basepath to store masks/checkpoints etc. in
        self.nxf_base_dir = Path.home() / ".nextflow" / "aiod"
        self.nxf_base_dir.mkdir(parents=True, exist_ok=True)
        self.nxf_store_dir = self.nxf_base_dir / "cache"
        self.nxf_store_dir.mkdir(parents=True, exist_ok=True)
        # Set the base Nextflow command
        # Ensures logs are stored in the right place (must be before run)
        self.nxf_base_cmd = (
            f"nextflow -log {str(self.nxf_base_dir / 'nextflow.log')} "
        )
        # Path to store the text file containing the image paths
        self.img_list_fpath = self.nxf_store_dir / "all_img_paths.csv"
        # Whether all images have been loaded
        # Needed to properly extract metadata
        self.all_loaded = False
        # Working directory for Nextflow
        self.nxf_work_dir = self.nxf_base_dir / "work"
        self.nxf_work_dir.mkdir(parents=True, exist_ok=True)
        # Dictionary to monitor progress of each image
        self.progress_dict = {}

        self.pipeline = pipeline
        # Available pipelines and their funcs
        self.pipelines = {
            "inference": self.setup_inference,
            "finetuning": self.setup_finetuning,
        }

    def create_box(self, variant: Optional[str] = None):
        # Create a drop-down box to select the execution profile
        self.nxf_profile_label = QLabel("Execution profile:")
        self.nxf_profile_label.setToolTip(
            format_tooltip("Select the execution profile to use.")
        )
        self.nxf_profile_box = QComboBox()
        # Get the available profiles from config dir
        config_dir = Path(__file__).parent / "Segment-Flow" / "profiles"
        avail_confs = [str(i.stem) for i in config_dir.glob("*.conf")]
        self.nxf_profile_box.addItems(avail_confs)
        self.layout().addWidget(self.nxf_profile_label, 0, 0)
        self.layout().addWidget(self.nxf_profile_box, 0, 1)
        # Add a checkbox for overwriting existing results
        self.overwrite_btn = QCheckBox("Overwrite existing results")
        self.overwrite_btn.setToolTip(
            format_tooltip(
                """
Select/enable to overwrite any previous results.

Exactly what is overwritten will depend on the pipeline selected. By default, any previous results matching the current setup will be loaded if possible. This can be disabled by ticking this box.
        """
            )
        )
        self.layout().addWidget(self.overwrite_btn, 1, 0, 1, 2)
        # Create a button to navigate to a directory to take images from
        self.nxf_run_btn = QPushButton("Run Pipeline!")
        self.nxf_run_btn.clicked.connect(self.run_pipeline)
        self.nxf_run_btn.setToolTip(
            format_tooltip(
                "Run the pipeline with the chosen organelle(s), model, and images."
            )
        )
        self.layout().addWidget(self.nxf_run_btn, 2, 0, 1, 2)

        # # Add a button for importing masks
        self.import_masks_btn = QPushButton("Import masks")
        self.import_masks_btn.clicked.connect(self.on_click_import)
        self.import_masks_btn.setToolTip(
            format_tooltip("Import segmentation masks.")
        )
        self.import_masks_btn.setEnabled(True)
        self.layout().addWidget(self.import_masks_btn, 3, 0)
        # Add a button for exporting masks
        self.export_masks_btn = QPushButton("Export masks")
        self.export_masks_btn.clicked.connect(self.on_click_export)
        self.export_masks_btn.setToolTip(
            format_tooltip("Export the segmentation masks to a directory.")
        )
        self.export_masks_btn.setEnabled(False)
        # TODO: Add dropdown for different formats to export to
        self.layout().addWidget(self.export_masks_btn, 3, 1)

        # Add progress bar
        self.pbar = QProgressBar()
        # Create the label associated with the progress bar
        self.pbar_label = QLabel("Progress: [--:--]")
        self.pbar_label.setToolTip(
            format_tooltip("Shows [elapsed<remaining] time for current run.")
        )
        # Add the label and progress bar to the layout
        self.layout().addWidget(self.pbar_label, 4, 0)
        self.layout().addWidget(self.pbar, 4, 1)
        # TQDM progress bar to monitor completion time
        self.tqdm_pbar = None
        # Add the layout to the main layout
        self.widget.setLayout(self.layout())

    def store_img_paths(self, img_paths):
        """
        Writes the provided image paths to a file to pass into Nextflow.

        TODO: May be subject to complete rewrite with dask/zarr
        """
        # Create container for metadata
        output = defaultdict(list)
        # Create container for knowing what images to track progress of
        self.progress_dict = {}
        # Extract info from each image
        for img_path in img_paths:
            # Get the mask layer name
            layer = self.parent.viewer.layers[img_path.stem]
            # Get the number of slices, channels, height, and width
            arr = layer.data.squeeze()
            if layer.rgb:
                res = arr.shape[:-1]
                channels = arr.shape[-1]
            else:
                res = arr.shape
                channels = 1
            if arr.ndim == 2:
                num_slices = 1
                H, W = res
            elif arr.ndim == 3:
                num_slices, H, W = res
            else:
                raise ValueError(
                    f"Unexpected number of dimensions for image {img_path}!"
                )
            output["img_path"].append(str(img_path))
            output["num_slices"].append(num_slices)
            output["height"].append(H)
            output["width"].append(W)
            output["channels"].append(channels)
        # Convert to a DataFrame and save
        df = pd.DataFrame(output)
        df.to_csv(self.img_list_fpath, index=False)
        # Store the total number of slices for progress bar
        self.total_slices = df["num_slices"].sum()

    def check_inference(self):
        """
        Checks that all the necessary parameters are set for inference.

        Checks that:
        - A task has been selected
        - A model has been selected
        - Data has been selected
        """
        if self.parent.selected_task is None:
            raise ValueError("No task/organelle selected!")
        if self.parent.selected_model is None:
            raise ValueError("No model selected!")
        if len(self.parent.subwidgets["data"].image_path_dict) == 0:
            raise ValueError("No data selected!")

    def setup_inference(self, nxf_params=None):
        """
        Runs the inference pipeline in Nextflow.

        `nxf_params` is a dict containing everything that Nextflow needs at the command line.

        `parent` is a parent widget, which is expected to contain the necessary info to construct `nxf_params`.
        """
        # First check that everything has been selected that needs to have been
        self.check_inference()
        # Store the selected task, model, and variant for execution
        self.parent.executed_task = self.parent.selected_task
        self.parent.executed_model = self.parent.selected_model
        self.parent.executed_variant = self.parent.selected_variant
        # Set the starting Nextflow command
        nxf_cmd = self.nxf_base_cmd + f"run {self.nxf_repo} -latest"
        # nxf_params can only be given when used standalone, which is rare
        if nxf_params is not None:
            return nxf_cmd, nxf_params
        # Construct the Nextflow params if not given
        parent = self.parent
        if parent.subwidgets["model"].model_config is None:
            config_path = parent.subwidgets["model"].get_model_config()
        else:
            config_path = parent.subwidgets["model"].model_config
        # Construct the proper mask directory path
        self.mask_dir_path = (
            self.nxf_store_dir
            / f"{parent.selected_model}"
            / f"{sanitise_name(parent.selected_variant)}_masks"
        )
        # Construct the params to be given to Nextflow
        nxf_params = {}
        nxf_params["img_dir"] = str(self.img_list_fpath)
        nxf_params["model"] = parent.selected_model
        nxf_params["model_config"] = config_path
        nxf_params["model_type"] = sanitise_name(parent.selected_variant)
        nxf_params["task"] = parent.selected_task
        # Extract the model checkpoint location and location type
        checkpoint_info = MODEL_TASK_VERSIONS[parent.selected_model][
            parent.selected_task
        ][parent.selected_variant]
        if "url" in checkpoint_info:
            nxf_params["model_chkpt_type"] = "url"
            nxf_params["model_chkpt_loc"] = checkpoint_info["url"]
            nxf_params["model_chkpt_fname"] = checkpoint_info["filename"]
        elif "dir" in checkpoint_info:
            nxf_params["model_chkpt_type"] = "dir"
            nxf_params["model_chkpt_loc"] = checkpoint_info["dir"]
            nxf_params["model_chkpt_fname"] = checkpoint_info["filename"]
        # No need to check if we are ovewriting
        if self.overwrite_btn.isChecked():
            proceed = True
            load_paths = []
            img_paths = self.parent.subwidgets["data"].image_path_dict.values()
            # Delete data in mask layers if present
            for img_path in img_paths:
                # Get the mask layer name
                layer_name = self.parent._get_mask_layer_name(
                    Path(img_path).stem
                )
                if layer_name in self.viewer.layers:
                    self.viewer.layers.remove(layer_name)
            # Delete current masks
            for mask_path in self.mask_dir_path.glob("*.npy"):
                mask_path.unlink()
        # Check if we already have all the masks
        else:
            proceed, img_paths, load_paths = self.parent.check_masks()
        # If some masks need loading, load them
        if load_paths:
            self.parent.create_mask_layers(img_paths=load_paths)
        # If we already have all the masks, don't run the pipeline
        if not proceed:
            show_info(
                f"Masks already exist for all files for segmenting {TASK_NAMES[parent.selected_task]} with {parent.selected_model} ({parent.selected_variant})!"
            )
            # Otherwise, until importing is fully sorted, the user just gets a notification and that's it
            return nxf_cmd, nxf_params, proceed, img_paths
        else:
            # Start the watcher for the mask files
            self.parent.watch_mask_files()
            return nxf_cmd, nxf_params, proceed, img_paths

    def setup_finetuning(self):
        """
        Runs the finetuning pipeline in Nextflow.
        """
        raise NotImplementedError

    def run_pipeline(self):
        if "data" not in self.parent.subwidgets:
            raise ValueError("Cannot run pipeline without data widget!")
        # Store the image paths
        self.image_path_dict = self.parent.subwidgets["data"].image_path_dict
        # Ensure the pipeline is valid
        assert (
            self.pipeline in self.pipelines.keys()
        ), f"Pipeline {self.pipeline} not found!"
        if self.all_loaded is False:
            show_info("Not all images have loaded, please wait...")
            return
        # Get the pipeline-specific stuff
        nxf_cmd, nxf_params, proceed, img_paths = self.pipelines[
            self.pipeline
        ]()
        # Don't run the pipeline if no green light given
        if not proceed:
            return
        # Store the image paths
        self.store_img_paths(img_paths=img_paths)
        # Add custom work directory
        if self.nxf_work_dir is not None:
            nxf_cmd += f" -w {self.nxf_work_dir}"
        # Add the selected profile to the command
        nxf_cmd += f" -profile {self.nxf_profile_box.currentText()}"
        # Add the parameters to the command
        for param, value in nxf_params.items():
            nxf_cmd += f" --{param}={value}"

        @thread_worker(
            connect={
                "returned": self._pipeline_finish,
                "errored": self._pipeline_fail,
            }
        )
        def _run_pipeline(nxf_cmd: str):
            # Run the command
            subprocess.run(nxf_cmd, shell=True, cwd=Path.home(), check=True)

        # Modify buttons during run
        self.export_masks_btn.setEnabled(False)
        # Disable the button to avoid issues
        # TODO: Enable multiple job execution, may require -bg flag?
        self.nxf_run_btn.setEnabled(False)
        # Update the button to signify it's running
        self.nxf_run_btn.setText("Running Pipeline...")
        self.init_progress_bar()
        # Run the pipeline
        _run_pipeline(nxf_cmd)

    def _reset_btns(self):
        """
        Resets the buttons to their original state.
        """
        self.nxf_run_btn.setText("Run Pipeline!")
        self.nxf_run_btn.setEnabled(True)
        self.export_masks_btn.setEnabled(True)

    def _pipeline_finish(self):
        # Add a notification that the pipeline has finished
        show_info("Pipeline finished!")
        self._reset_btns()

    def _pipeline_fail(self, exc):
        show_info("Pipeline failed! See terminal for details")
        print(exc)
        self._reset_btns()

    def init_progress_bar(self):
        # Set the values of the Qt progress bar
        self.pbar.setRange(0, self.total_slices)
        self.pbar.setValue(0)
        # Initialise the tqdm progress bar to monitor time
        self.tqdm_pbar = tqdm.tqdm(total=self.total_slices)
        # Reset the label
        self.pbar_label.setText("Progress: [--:--]")

    def update_progress_bar(self):
        # Update the progress bar to the current number of slices
        curr_slices = sum(self.progress_dict.values())
        self.pbar.setValue(curr_slices)
        self.tqdm_pbar.update(curr_slices - self.tqdm_pbar.n)
        # Update the label
        elapsed = self.tqdm_pbar.format_dict["elapsed"]
        rate = (
            self.tqdm_pbar.format_dict["rate"]
            if self.tqdm_pbar.format_dict["rate"]
            else 1
        )
        remaining = (self.tqdm_pbar.total - self.tqdm_pbar.n) / rate
        self.pbar_label.setText(
            f"Progress: [{self.tqdm_pbar.format_interval(elapsed)}<{self.tqdm_pbar.format_interval(remaining)}]"
        )

    def on_click_import(self):
        """
        Callback for when the import button is clicked. Opens a dialog to select mask files to import.

        Expectation is that these come from the Nextflow and are therefore .npy files. For anything external, they can be added to Napari as normal.

        TODO: Current disabled, as arbitrary import makes it harder to allow partial pipeline running.
        """
        fnames, _ = QFileDialog.getOpenFileNames(
            self,
            caption="Select mask files to import",
            directory=str(Path.home()),
            filter="Numpy files (*.npy)",
        )
        for fname in fnames:
            mask_arr = np.load(fname)
            self.viewer.add_labels(
                mask_arr,
                name=Path(fname).stem.replace("_all", ""),
                visible=True,
            )

    def on_click_export(self):
        """
        Callback for when the export button is clicked. Opens a dialog to select a directory to save the masks to.
        """
        export_dir = QFileDialog.getExistingDirectory(
            self, caption="Select directory to save masks", directory=None
        )
        # Get the current viewer
        viewer = self.parent.viewer if self.parent is not None else None
        # TODO: How to handle if parent doesn't exist? Will this ever happen?
        # Get all the mask layers
        mask_layers = []
        for img_name in self.image_path_dict:
            layer_name = self.parent._get_mask_layer_name(img_name)
            if layer_name in viewer.layers:
                mask_layers.append(viewer.layers[layer_name])
        # Extract the data from each of the layers, and save the result in the given folder
        # NOTE: Will also need adjusting for the dask/zarr rewrite
        if mask_layers:
            count = 0
            for mask_layer in mask_layers:
                np.save(
                    Path(export_dir) / f"{mask_layer.name}.npy",
                    mask_layer.data,
                )
                count += 1
            show_info(f"Exported {count} mask files to {export_dir}!")
        else:
            show_info("No mask layers found!")
