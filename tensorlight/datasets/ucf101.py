import sys
import os
import random

import numpy as np
import tensorflow as tf
import tensorlight as light
import base


UCF101_URL = 'http://crcv.ucf.edu/data/UCF101/UCF101.rar'
UCF101_SPLITS_URL = 'http://crcv.ucf.edu/data/UCF101/UCF101TrainTestSplits-RecognitionTask.zip'
UCF101_TRAINLIST = "trainlist03.txt"
UCF101_TESTLIST = "testlist03.txt"

FRAME_HEIGHT = 240
FRAME_WIDTH = 320
FRAME_CHANNELS = 3

MAX_TRIES = 100
MIN_L2_DIFF_PER_FRAME = 25.0 # of image value range [-1, 1]


class UCF101TrainDataset(base.AbstractQueueDataset):
    """UCF-101 dataset that creates a bunch of binary frame sequences
       and uses a file queue for multi-threaded input reading.
       
       References: http://crcv.ucf.edu/data/UCF101.php
    """
    def __init__(self, data_dir, input_seq_length=5, target_seq_length=5,
                 image_scale_factor=1.0, gray_scale=False,
                 min_examples_in_queue=1024, queue_capacitiy=2048, num_threads=16,
                 serialized_sequence_length=30, do_distortion=True, crop_size=None,
                 skip_less_movement=True):
        """Creates a training dataset instance that uses a queue.
        Parameters
        ----------
        data_dir: str
            The dataset root path to store the data.
        input_seq_length: int, optional
            The length of the input sequence.
        target_seq_length: length
            The length of the target sequence.
        image_scale_factor: float in range (0.0, 1.0], optional
            The image scale size, how the data should be scaled to.
        gray_scale: Boolean, optional
            Whether we scale the image to gray or not.
        min_examples_in_queue: int, optional
            The minimum examples that have to be in the queue.
            A higher value ensures a good mix.
        queue_capacitiy: int, optional
            The maximum capacity of the input queue.
        num_threads: int, optional
            The number of threads to generate the inputs.
        serialized_sequence_length: int, optional
            The sequence length of each serialized file.
        do_distortion: Boolean, optional
            Whether image distortion should be performed or not.
            Can have a very bad influence on performance.
        crop_size: tuple(int) or None, optional
            The size (height, width) to randomly crop the images.
        skip_less_movement: Boolean, optional
            Skip frame sequences where there is too less movement in the inputs at all,
        """
        image_size = [int(FRAME_HEIGHT * image_scale_factor),
                      int(FRAME_WIDTH * image_scale_factor),
                      1 if gray_scale else FRAME_CHANNELS]
        
        if crop_size is not None:
            assert image_size[0] > crop_size[0] and image_size[1] > crop_size[1], \
                "Image size has to be larger than the crop size."
        
        
        self._serialized_sequence_length = serialized_sequence_length
        self._do_distortion = do_distortion
        self._crop_size = crop_size
        self._skip_less_movement = skip_less_movement
        self._data_img_size = image_size
        
        rar_path = light.utils.data.download(UCF101_URL, data_dir)

        dataset_path = light.utils.data.extract(rar_path, data_dir, unpacked_name='UCF-101')
        self._data_dir = dataset_path
            
        zip_path = light.utils.data.download(UCF101_SPLITS_URL, data_dir)
        splits_path = light.utils.data.extract(zip_path, data_dir, unpacked_name='ucfTrainTestlist')
            
        # generate frame sequences
        train_files = UCF101TrainDataset._read_train_splits(splits_path)
        dataset_size, seq_files = light.utils.data.preprocess_videos(dataset_path, light.utils.data.SUBDIR_TRAIN,
                                                                  train_files,
                                                                  [FRAME_HEIGHT, FRAME_WIDTH, FRAME_CHANNELS],
                                                                  serialized_sequence_length,
                                                                  gray_scale, image_scale_factor)
        self._file_name_list = seq_files
        
        if crop_size is None:
            input_shape = [input_seq_length, image_size[0], image_size[1], image_size[2]]
            target_shape = [target_seq_length, image_size[0], image_size[1], image_size[2]]
        else:
            input_shape = [input_seq_length, crop_size[0], crop_size[1], image_size[2]]
            target_shape = [target_seq_length, crop_size[0], crop_size[1], image_size[2]]
        
        super(UCF101TrainDataset, self).__init__(data_dir, dataset_size, input_shape, target_shape,
                                                min_examples_in_queue, queue_capacitiy, num_threads)
    
    @staticmethod
    def _read_train_splits(dir_path):
        """Reads the filepaths of the train split."""
        train_files = []

        filepath = os.path.join(dir_path, UCF101_TRAINLIST)
        with open(filepath) as f:
            for line in f:
                train_files.append(line.split()[0])
        return train_files
    
    def _read_record(self, filename_queue):
        
        class FrameSeqRecord(object):
            pass
        
        record = FrameSeqRecord()
        record.height = self._data_img_size[0]
        record.width = self._data_img_size[1]
        record.depth = self._data_img_size[2]
        
        input_seq_length = self.input_shape[0]
        target_seq_length = self.target_shape[0]
        total_seq_length = input_seq_length + target_seq_length

        frame_bytes = record.height * record.width * record.depth
        record_bytes = frame_bytes * (total_seq_length)
        total_file_bytes = frame_bytes * self._serialized_sequence_length

        with tf.name_scope('read_record'):
            reader = tf.FixedLengthRecordReader(total_file_bytes)

            record.key, value = reader.read(filename_queue)
            decoded_record_bytes = tf.decode_raw(value, tf.uint8)

            decoded_record_bytes = tf.reshape(decoded_record_bytes,
                                              [self._serialized_sequence_length, record.height, record.width, record.depth])

            # calculcate tensors [start, 0, 0, 0]
            rnd_start_index = tf.to_int32(tf.random_uniform([1], 0, self._serialized_sequence_length - (total_seq_length), 
                                                            tf.int32))
            seq_start_offset = tf.SparseTensor(indices=[[0]], values=rnd_start_index, dense_shape=[4])
            sequence_start = tf.sparse_tensor_to_dense(seq_start_offset)

            # take a random slice of frames as input
            record.data = tf.slice(decoded_record_bytes, sequence_start,
                                   [total_seq_length, record.height, record.width, record.depth])
            return record

    @light.utils.attr.override
    def get_batch(self, batch_size):
        # Generate a batch of sequences and labels by building up a queue of examples.
        with tf.name_scope('preprocessing'):
            filename_queue = tf.train.string_input_producer(self._file_name_list,
                                                            capacity=256)
            seq_record = self._read_record(filename_queue)  

            # convert to float of scale [0.0, 1.0]
            seq_data = tf.cast(seq_record.data, tf.float32)
            seq_data = seq_data / 255.0
    
            input_seq_length = self.input_shape[0]
            target_seq_length = self.target_shape[0]
            total_seq_length = input_seq_length + target_seq_length
            
            """if self._crop_size is not None:
                with tf.name_scope('random_crop'):
                    seq_data = tf.random_crop(seq_data,
                                              [total_seq_length,
                                               self._crop_size[0],
                                               self._crop_size[1],
                                               self.input_shape[3]])"""
            
            if self._crop_size is not None: 
                with tf.name_scope('random_crop'):
                    def body(c, sdata, cropped):
                        cropped =  tf.random_crop(sdata,
                                                [total_seq_length,
                                                 self._crop_size[0],
                                                 self._crop_size[1],
                                                 self.input_shape[3]])
                        c = tf.maximum(0, c - 1)
                        return c, sdata, cropped
                
                    def condition(c, sdata, cropped):
                        zero = tf.constant(0, dtype=tf.int32)
                        not_max_retries = tf.not_equal(zero, c)
                        # loop over inputs only
                        diff = 0.0
                        for t in xrange(input_seq_length - 1):
                            # multiply difference by to to simulate scale [-1, 1] by using [0, 1]
                            sse = tf.square(tf.sub(cropped[t + 1,:,:,:], cropped[t,:,:,:]) * 2)
                            diff += tf.reduce_sum(sse)
                        limit = tf.convert_to_tensor(MIN_L2_DIFF_PER_FRAME * input_seq_length, tf.float32)
                        not_enough_movement = tf.less(diff, limit, name="min_motion_check")
                        return tf.logical_and(not_max_retries, not_enough_movement)
                    
                    # crop until we finde some movement
                    first_crop = tf.random_crop(seq_data,
                                                [total_seq_length,
                                                 self._crop_size[0],
                                                 self._crop_size[1],
                                                 self.input_shape[3]])

                    first_crop.set_shape((total_seq_length,
                                               self._crop_size[0],
                                               self._crop_size[1],
                                               self.input_shape[3]))

                    if self._skip_less_movement:
                        counter = tf.Variable(MAX_TRIES, dtype=tf.int32, trainable=False, name="loop_counter")
                        _, _, seq_data_cropped = tf.while_loop(condition, body, [counter, seq_data, first_crop])
                        seq_data = seq_data_cropped
                        # make shape fully-defined after loop
                        seq_data.set_shape((total_seq_length,
                                                   self._crop_size[0],
                                                   self._crop_size[1],
                                                   self.input_shape[3]))
                    else:
                        seq_data = first_crop
                    
            if self._do_distortion:
                with tf.name_scope('distortion'):
                    images_to_distort = tf.unpack(seq_data)

                    distorted_images = light.image.equal_random_distortion(images_to_distort)
                    sequence_inputs = tf.pack(distorted_images[0:input_seq_length], axis=0)
                    sequence_targets = tf.pack(distorted_images[input_seq_length:], axis=0)
            else:
                sequence_inputs = seq_data[0:input_seq_length,:,:,:]
                sequence_targets = seq_data[input_seq_length:,:,:,:]

        batchx, batchy = light.inputs.generate_batch(sequence_inputs, sequence_targets,
                                        batch_size,
                                        self._min_examples_in_queue, self._queue_capacitiy,
                                        shuffle=True, num_threads=self._num_threads)
        return batchx, batchy

    @property
    def serialized_sequence_length(self):
        """Gets the serialized sequence length"""
        return self._serialized_sequence_length
    
    @property
    def do_distortion(self):
        """Gets whether distorion is activated."""
        return self._do_distortion

    
def enough_l2_movement(frames):
    """Checks if the frames array has enough movement to filter
       static image examples.
    """
    #dived by 127.5 to simulate scale [-1, 1] using image with scale [0, 255]
    frames_scaled = frames / 127.5
    diff = 0
    n = frames_scaled.shape[0]
    for i in reversed(xrange(n - 1)):
        diff += np.sum(np.square(frames_scaled[i] - frames_scaled[i + 1]))
        
        if diff >= MIN_L2_DIFF_PER_FRAME * n:
            return True
    return False


class UCF101BaseEvaluationDataset(base.AbstractDataset):    
    """UCF-101 dataset base class for evaluation, which creates a bunch of
       binary frame sequences.
       The data is not qualitatively-augmented with contrast, brightness,
       to allow better comparability between single validations.
       But it allows to use allows to use random cropping, as well as
       doubling the data quantitatively by using both, flipped and unflipped
       images.
       
       References: http://crcv.ucf.edu/data/UCF101.php
    """
    def __init__(self, data_dir, subdir, input_seq_length=5, target_seq_length=5,
                 image_scale_factor=1.0, gray_scale=False,
                 serialized_sequence_length=30, double_with_flipped=False,
                 crop_size=None, repetitions_per_epoche=4, skip_less_movement=True):
        """Creates a dataset instance.
        Parameters
        ----------
        data_dir: str
            The path where the data will be stored.
        subdir: str
            The subdirectory where the serialized data will be stored.
        input_seq_length: int, optional
            The length of the input sequence.
        target_seq_length: length
            The length of the target sequence.
        image_scale_factor: float in range (0.0, 1.0], optional
            The image scale size, how the data should be scaled to.
        gray_scale: Boolean, optional
            Whether we scale the image to gray or not.
        serialized_sequence_length: int, optional
            The sequence length of each serialized file.
        double_with_flipped: Boolean, optional
            Whether quantitative augmentation should be performed or not.
            It doubles the dataset_size by including the horizontal flipped
            images as well.
        crop_size: tuple(int) or None, optional
            The size (height, width) to randomly crop the images.
        repetitions_per_epoche: int, optioal
            Virtually increase the dataset size by a factor. We useually take only a small portion
            of the frame sequence. And in case of random cropping, we only take a small part of the image. 
            That's why it is important to reuse these frame sequences multiple times, as we use a random
            part each time. If we would not, Testing could vary each evaluation a lot.
        skip_less_movement: Boolean, optional
            Skip frame sequences where there is too less movement in the inputs at all.
        """
        image_size = [int(FRAME_HEIGHT * image_scale_factor),
                      int(FRAME_WIDTH * image_scale_factor),
                      1 if gray_scale else FRAME_CHANNELS]
        
        if crop_size is not None:
            assert image_size[0] > crop_size[0] and image_size[1] > crop_size[1], \
                "Image size has to be larger than the crop size."
        
        self._serialized_sequence_length = serialized_sequence_length
        self._double_with_flipped = double_with_flipped
        self._crop_size = crop_size
        self._skip_less_movement = skip_less_movement
        self._data_img_size = image_size
        
        rar_path = light.utils.data.download(UCF101_URL, data_dir)

        dataset_path = light.utils.data.extract(rar_path, data_dir, unpacked_name='UCF-101')
        self._data_dir = dataset_path
            
        zip_path = light.utils.data.download(UCF101_SPLITS_URL, data_dir)
        splits_path = light.utils.data.extract(zip_path, data_dir, unpacked_name='ucfTrainTestlist')

        # generate frame sequences
        (eval_files) = UCF101BaseEvaluationDataset._read_eval_splits(splits_path)
        eval_index = 0 if subdir == light.utils.data.SUBDIR_VALID else 1
        dataset_size, seq_files = light.utils.data.preprocess_videos(dataset_path, subdir, eval_files[eval_index],
                                                                  [FRAME_HEIGHT, FRAME_WIDTH, FRAME_CHANNELS],
                                                                  serialized_sequence_length,
                                                                  gray_scale, image_scale_factor)
        self._file_name_list = seq_files
        
        # even if the dataset size is doubled, use the original
        # size for the indices list to reduce its size...
        self.real_dataset_size = dataset_size
        self._indices = range(dataset_size)
        self._row = 0  # Note: if 'double_with_flipped' is active,
                       #       the row-index overflows the (internal) dataset size
        
        # ...but for the outside, fake to have to doubled size.
        if double_with_flipped:
            dataset_size *= 2
        dataset_size *= repetitions_per_epoche
        
        if crop_size is None:
            input_shape = [input_seq_length, image_size[0], image_size[1], image_size[2]]
            target_shape = [target_seq_length, image_size[0], image_size[1], image_size[2]]
        else:
            input_shape = [input_seq_length, crop_size[0], crop_size[1], image_size[2]]
            target_shape = [target_seq_length, crop_size[0], crop_size[1], image_size[2]]
        
        super(UCF101BaseEvaluationDataset, self).__init__(data_dir, dataset_size, input_shape, target_shape)

    @staticmethod
    def _read_eval_splits(dir_path):
        """Reads the filepaths of the valid/test splits.
           Alternated throught the file list, 1/3 is considered
           as validation and 2/3 as test data.
        """
        test_files = []
        valid_files = []

        filepath = os.path.join(dir_path, UCF101_TESTLIST)
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i % 3 == 0:
                    valid_files.append(line.split()[0])
                else:    
                    test_files.append(line.split()[0])

        return valid_files, test_files
        
    @light.utils.attr.override
    def get_batch(self, batch_size):
        fake_size = self.size
        data_size = self.real_dataset_size
        
        if self._row + batch_size >= fake_size:
            self.reset()
        
        # we interate through the list a couple of times, due to double_with_flipped
        # and repetitions_per_epoche -> use modulo
        start = self._row % data_size
        end = (start + batch_size) % data_size
        if start > end:
            ind_range = self._indices[start:] + self._indices[:end]
        else:
            ind_range = self._indices[start:end]
               
        # ensure we have the correct batch-size
        assert len(ind_range) == batch_size, "Assertion of batch_size and ind_range failed."
        
        # get next filenames
        file_names = [self._file_name_list[i] for i in ind_range]
        
        # load serialized sequences
        seq_input_list = []
        seq_target_list = []
        
        for i, f in enumerate(file_names):
            virtual_row = self._row + i
                                       
            current = light.utils.image.read_as_binary(f, dtype=np.uint8)
            current = np.reshape(current, [self.serialized_sequence_length] + list(self._data_img_size))
            
            # select random part of the sequence with length of inputs+targets
            inputs_length = self.input_shape[0]
            targets_length = self.target_shape[0]
            total_length = inputs_length + targets_length
            start_t = random.randint(0, self.serialized_sequence_length - total_length)
            current = current[start_t:(start_t + total_length)]
            
            if self._crop_size is not None:
                for retry in xrange(MAX_TRIES):
                    # do equal random crop
                    offset_x = random.randint(0, self._data_img_size[1] - self._crop_size[1])
                    offset_y = random.randint(0, self._data_img_size[0] - self._crop_size[0])

                    crop = current[:, offset_y:(offset_y + self._crop_size[0]),
                                   offset_x:(offset_x + self._crop_size[1]),:]

                    if self._skip_less_movement:
                        current_inputs = crop[:inputs_length]
                        if not enough_l2_movement(current_inputs):
                            continue
                    
                    # break to stop retrying
                    break
                
                current = crop

            if self.double_with_flipped:
                # do flipping: every even frame is 1st part, and every odd frame in 2nd part
                #              of our virtual row index
                if virtual_row < data_size and virtual_row % 2 == 0 \
                   or virtual_row >= data_size and virtual_row % 2 == 1:
                    current = current[:,:,::-1,:] # horizontal flip
            
            seq_input_list.append(current[0:inputs_length])
            seq_target_list.append(current[inputs_length:(inputs_length + total_length)])
        
        input_sequence = np.stack(seq_input_list)
        target_sequence = np.stack(seq_target_list)
        
        # convert to float of scale [0.0, 1.0]
        inputs = input_sequence / np.float32(255)
        targets = target_sequence / np.float32(255)
                
        # delayed inc of row-counter because it is used in the loop
        self._row += batch_size
        
        return inputs, targets
    
    @light.utils.attr.override
    def reset(self):
        self._row = 0
        np.random.shuffle(self._indices)
        
    @property
    def serialized_sequence_length(self):
        """Gets the serialized sequence length"""
        return self._serialized_sequence_length
    
    @property
    def double_with_flipped(self):
        """Gets whether doubling the datasize by using the flipped
           images as well is activated.
        """
        return self._double_with_flipped
    
    
class UCF101ValidDataset(UCF101BaseEvaluationDataset):    
    """UCF-101 validation dataset that creates a bunch of binary frame sequences.
       The data is not qualitatively-augmented with contrast, brightness,
       to allow better comparability between single validations.
       But it allows to use allows to use random cropping, as well as
       doubling the data quantitatively by using both, flipped and unflipped
       images.
       
       References: http://crcv.ucf.edu/data/UCF101.php
    """
    def __init__(self, data_dir, input_seq_length=5, target_seq_length=5,
                 image_scale_factor=1.0, gray_scale=False,
                 serialized_sequence_length=30, double_with_flipped=False,
                 crop_size=None, repetitions_per_epoche=4, skip_less_movement=True):
        """Creates a validation dataset instance.
        Parameters
        ----------
        data_dir: str
            The path where the data will be stored.
        input_seq_length: int, optional
            The length of the input sequence.
        target_seq_length: length
            The length of the target sequence.
        image_scale_factor: float in range (0.0, 1.0], optional
            The image scale size, how the data should be scaled to.
        gray_scale: Boolean, optional
            Whether we scale the image to gray or not.
        serialized_sequence_length: int, optional
            The sequence length of each serialized file.
        double_with_flipped: Boolean, optional
            Whether quantitative augmentation should be performed or not.
            It doubles the dataset_size by including the horizontal flipped
            images as well.
        crop_size: tuple(int) or None, optional
            The size (height, width) to randomly crop the images.
        repetitions_per_epoche: int, optioal
            Virtually increase the dataset size by a factor. We useually take only a small portion
            of the frame sequence. And in case of random cropping, we only take a small part of the image. 
            That's why it is important to reuse these frame sequences multiple times, as we use a random
            part each time. If we would not, Testing could vary each evaluation a lot.
        skip_less_movement: Boolean, optional
            Skip frame sequences where there is too less movement in the inputs at all.
        """
        super(UCF101ValidDataset, self).__init__(data_dir, light.utils.data.SUBDIR_VALID,
                                                 input_seq_length, target_seq_length,
                                                 image_scale_factor, gray_scale, serialized_sequence_length,
                                                 double_with_flipped, crop_size,
                                                 repetitions_per_epoche, skip_less_movement)
        
        
class UCF101TestDataset(UCF101BaseEvaluationDataset):    
    """UCF-101 test dataset that creates a bunch of binary frame sequences.
       The data is not qualitatively-augmented with contrast, brightness,
       to allow better comparability between single validations.
       But it allows to use allows to use random cropping, as well as
       doubling the data quantitatively by using both, flipped and unflipped
       images.
       
       References: http://crcv.ucf.edu/data/UCF101.php
    """
    def __init__(self, data_dir, input_seq_length=5, target_seq_length=5,
                 image_scale_factor=1.0, gray_scale=False,
                 serialized_sequence_length=30, double_with_flipped=False,
                 crop_size=None, repetitions_per_epoche=8, skip_less_movement=True):
        """Creates a validation dataset instance.
        Parameters
        ----------
        data_dir: str
            The path where the data will be stored.
        input_seq_length: int, optional
            The length of the input sequence.
        target_seq_length: length
            The length of the target sequence.
        image_scale_factor: float in range (0.0, 1.0], optional
            The image scale size, how the data should be scaled to.
        gray_scale: Boolean, optional
            Whether we scale the image to gray or not.
        serialized_sequence_length: int, optional
            The sequence length of each serialized file.
        double_with_flipped: Boolean, optional
            Whether quantitative augmentation should be performed or not.
            It doubles the dataset_size by including the horizontal flipped
            images as well.
        crop_size: tuple(int) or None, optional
            The size (height, width) to randomly crop the images.
        repetitions_per_epoche: int, optioal
            Virtually increase the dataset size by a factor. We useually take only a small portion
            of the frame sequence. And in case of random cropping, we only take a small part of the image. 
            That's why it is important to reuse these frame sequences multiple times, as we use a random
            part each time. If we would not, Testing could vary each evaluation a lot.
        skip_less_movement: Boolean, optional
            Skip frame sequences where there is too less movement in the inputs at all.
        """
        super(UCF101TestDataset, self).__init__(data_dir, light.utils.data.SUBDIR_TEST,
                                                input_seq_length, target_seq_length,
                                                image_scale_factor, gray_scale, serialized_sequence_length, 
                                                double_with_flipped, crop_size,
                                                repetitions_per_epoche, skip_less_movement)