import os
import math

import cv2
import numpy as np
import tensorlight as tt

import skvideo.io
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip


class VideoReader():
    """Video file reader class using OpenCV."""
    def __init__(self, filename, start_frame=0):
        """Creates a VideoReader instance.
        Parameters
        ----------
        filename: str
            The file path to the video.
        start_frame: int, optional
            The frame where to start the video.
        """
        if not os.path.isfile(filename):
            print("Video file {} not found.".format(filename))
        
        self._filename = filename
        
        # load the video data
        self._video = None
        if self._video is None:
            self.read_video()

        # select the start frame
        self._frame_idx = start_frame
        
    def __enter__(self):
        """Enters the context manager."""
        return self
    
    def __exit__(self, type, value, traceback):
        """Exits the context manager and releases the video."""
        self.release()
        
    def next_frame(self, scale=1.0):
        """Reads the next frame from the video.
        Parameters
        ----------
        scale: float, optional
            The scale value to resize the frame image.
        Returns
        ----------
        image: ndarray(uint8)
            Returns an ndarray of the image or None in case of an error.
        """
        if self._video is None or self._video.shape[0] <= self._frame_idx:
            return None
        
        frame = self._video[self._frame_idx]
        self._frame_idx += 1
        
        frame = tt.utils.image.resize(frame, scale)
        return frame
        
    def read_video(self):
        if self._video is None:
            video = skvideo.io.vread(self._filename)
            if video is None:
                raise IOError("Could not load video file.")
            else:
                self._video = video
        return self._video
        
    def skip_frames(self, count=1):
        """Skips the next frames from the video.
        Parameters
        ----------
        count: int, optional
            The number of frames to skip.
        """
        self.goto_frame(self._frame_idx + count)
                
    def goto_frame(self, frame_idx):
        """Go to a specific frame."""
        self._frame_idx = frame_idx
        
    def release(self):
        """Releases the video file resources."""
        if self._video is not None:
            del self._video
    
    @property
    def frames_length(self):
        """Returns the total frames length of the video."""
        return self._video.shape[0]
    
    @property
    def frame_idx(self):
        """Returns the current frame index of the video."""
        return self._frame_idx
    
    @property
    def frames_left(self):
        """Returns the number of frames that are left."""
        return self.frames_length - self.frame_idx


class VideoWriter():
    MIN_WIDTH = 128
    MIN_HEIGHT = 128
    FF_MIN_BUFFER_SIZE = 16384  # from OpenCV C++ code
    
    """Video writer class using OpenCV."""
    def __init__(self, filename,
                 fps=24.0, frame_size=(240, 320), is_color=True):
        """Creates a VideoWriter instance.
        Parameters
        ----------
        filename: str
            The file path to store the video to write. Currently only
            the file extension ".avi" is supported.
        fps: float, optional
            The frame rate of the video in frames/seconds.
        frame_size: tuple(height,width), optional
            The frame size of the video.
        is_color: Boolean, optional
            Indicates whether the video has colors or is just gray scaled.
        """
        self._filename = filename
        
    def __enter__(self):
        """Enters the context manager."""
        return self
    
    def __exit__(self, type, value, traceback):
        """Exits the context manager and releases the video."""
        self.release()
        
    def write(self, frames):
        """Writes a video frame to the file.
        Parameters
        ----------
        frame: ndarray(uint8)
            The video frame to write.
        """
        frames = tt.utils.image.cast(frames)
        skvideo.io.vwrite(self._filename, frames)
  
    def release(self):
        """Releases the video file resources."""
        pass



def write_gif(filepath, images, fps=24):
    """Saves a sequence of images as an animated GIF.
    Parameters
    ----------
    filepath: str
        The filepath ending with *.gif where to save the file.
    images: list(3-D array) or 4-D array
        A list of images or a 4-D array where the first dimension
        represents the time axis.
    fps: int, optional
        The frame rate.
    """
    # to list
    if not isinstance(images, list):
        splitted = np.split(images, images.shape[0])
        images = [np.squeeze(s, axis=(0,)) for s in splitted]
    elif len(images) == 0:
        return
        
    # ensure directory exists
    dirpath = os.path.dirname(filepath)
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)
        
    # scale factor for float
    factor = 1
    if tt.utils.image.is_float_image(images[0]):
        factor = 255

    clip = ImageSequenceClip([img * factor for img in images], fps=fps)
    clip.write_gif(filepath, verbose=False)

    
def write_multi_gif(filepath, images_list, fps=24, pad_value=0, pad_width=2):
    """Saves multiple sequences of images as a single animated GIF.
       The single clips will be padded and combined in a row.
    Parameters
    ----------
    filepath: str
        The filepath ending with *.gif where to save the file.
    images_list: list(list(3-D array)) or list(4-D array)
        A list of list(images) or a list(4-D array) where the first dimension
        represents the time axis. The internal lists have to have equal length.
    fps: int, optional
        The frame rate.
    pad_value: int, optional
        The value of the image padding in range [0, 255].
    pad_width: int, optional
        The width of the padding.
    """
    max_length = 0
    for i in xrange(len(images_list)):
        # to list of list
        if not isinstance(images_list[i], list):  
            splitted = np.split(images_list[i], images_list[i].shape[0])
            images_list[i] = [np.squeeze(s, axis=(0,)) for s in splitted]
        max_length = max(max_length, len(images_list[i]))
    
    # pad images
    padded_seq_list = []
    for i in xrange(len(images_list)):
        seq_list = []
        for j in xrange(max_length):
            if j < len(images_list[i]):
                seq_list.append(np.pad(images_list[i][j],
                                       ((pad_width, pad_width), (pad_width, pad_width), (0,0)),
                                       mode="constant", constant_values=pad_value))
            else:
                shape = images_list[0][0].shape
                seq_list.append(np.ones((shape[0] + 2*pad_width, shape[1] + 2*pad_width, shape[2])) * pad_value)
        padded_seq_list.append(seq_list)
        
    # concatenate
    concat_list = []
    for frame_idx in xrange(len(padded_seq_list[0])):
        single_frame_of_each_seq = [row[frame_idx] for row in padded_seq_list]
        concat_list.append(np.concatenate(single_frame_of_each_seq, axis=1))
    
    write_gif(filepath, concat_list, fps)

    
def _to_single_sequence(images, pad_value, pad_width, seq_length):
    # to list
    if not isinstance(images, list):
        splitted = np.split(images, images.shape[0])
        images = [np.squeeze(s, axis=(0,)) for s in splitted]
      
    # pad images
    padded_list = []
    for i in xrange(seq_length):
        if i < len(images):
            padded_list.append(np.pad(images[i],
                                      ((pad_width, pad_width), (pad_width, pad_width), (0,0)),
                                      mode="constant", constant_values=pad_value))
        else:
            shape = images[0].shape
            padded_list.append(np.ones((shape[0] + 2*pad_width, shape[1] + 2*pad_width, shape[2])) * pad_value)
            
    # concatenate
    return np.concatenate(padded_list, axis=1)
    
def write_image_sequence(filepath, images, pad_value=0, pad_width=2):
    """Saves a sequence of images as a single image file.
    Parameters
    ----------
    filepath: str
        The filepath ending with *.gif where to save the file.
    images: list(3-D array) or 4-D array
        A list of images or a 4-D array where the first dimension
        represents the time axis.
    pad_value: int, optional
        The value of the image padding in range [0, 255].
    pad_width: int, optional
        The width of the padding.
    """
    concat_image = _to_single_sequence(images, pad_value, pad_width, len(images))
    tt.utils.image.write(filepath, concat_image)
    

def write_multi_image_sequence(filepath, images_list, pad_value=0, pad_width=2):
    """Saves multiple sequences of images as a single image file.
    Parameters
    ----------
    filepath: str
        The filepath ending with *.gif where to save the file.
    images_list: list(list(3-D array)) or list(4-D array)
        A list of list(images) or a list(4-D array) where the first dimension
        represents the time axis. The internal lists have to have equal length.
    pad_value: int, optional
        The value of the image padding in range [0, 255].
    pad_width: int, optional
        The width of the padding.
    """
    max_length = 0
    for seq in images_list:
        if not isinstance(seq, list):
            max_length = max(max_length, seq.shape[0])
        else:
            max_length = max(max_length, len(seq))
    
    seq_list = []
    for i in xrange(len(images_list)):
        seq_list.append(_to_single_sequence(images_list[i], pad_value, pad_width, max_length))
        
    # concatenate
    concat_image = np.concatenate(seq_list, axis=0)
        
    tt.utils.image.write(filepath, concat_image)