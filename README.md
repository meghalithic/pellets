# Computer vision to extract width of _Neotoma_ pellets

Measuring pellets is a time consuming process. This project's aim is to develop a CV program to rapidly extract width measurements.

We used Claude to create the [measure_pellets.py](https://github.com/meghalithic/pellets/blob/main/pellet_measure/measure_pellets.py) and [requirements.txt](https://github.com/meghalithic/pellets/blob/main/pellet_measure/requirements.txt) code (see [markdown file](https://github.com/meghalithic/pellets/blob/main/pellet_measurement_notes.md)). 

I instructed it on what parameters I want:
- ignore the ID card
- ignore the scale bar
- create a scale

The program will open up the images one by one to set the scale and select parts of the image, such as the ID card and ruler, to exclude.

The outputs are an annotated image appended with "_annotated" and a measurements.csv file.

## Experiment
I have a series of images:
- those with known measurements
- those with varying number of pellets
- those with varying degrees of sorting done

The purpose of these mini experiments is to see how well the CV performs at identifying and measuring individual pellets.

## How to run it
`cd ~/to/folder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python measure_pellets.py ./photos/
deactivate`

to use later:
`source venv/bin/activate`

`--same-scale`: new images automatically get the same scale as used before

`--redo`: when want to rescale and create new outlines to ignore

`--exclude`: allows you to exclude the ID card and ruler in the measurements

This is how I use it:

Populate the folder "photos" with a single image to create the scale by running `python measure_pellets.py ./photos/ --same-scale --exclude --redo`

Then, add the rest of the images to "photos" and run `python measure_pellets.py ./photos/ --same-scale --exclude` to then select out the ID card and scale bar in each image, but keep the same scale.
