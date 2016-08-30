import numpy as np
import tensortools as tt

from abc import ABCMeta, abstractmethod, abstractproperty

class AbstractDataset(object):
    __metaclass__ = ABCMeta

    def __init__(self, data, targets, dataset_size):
        """Creates a dataset instance.
        Reference: Based on Srivastava et al.
                   http://www.cs.toronto.edu/~nitish/unsupervised_video/
        Parameters
        ----------
        ... TODO: describe parameters of this classes.
        targets can be None: e.g. for image sequences or generated data
        """
        self._dataset_size = dataset_size

        self._data = data
        self._targets = targets
        self._indices = np.arange(data.shape[0])
        self._row = 0
        self.reset()

    @property
    def input_dims(self):
        return np.prod(self.input_shape)
    
    @property
    def target_dims(self):
        return np.prod(self.target_shape)
    
    @abstractproperty
    def input_shape(self):
        pass # TODO: implement it here from self._data? But can be overriden in sub class (moving mnist)
    
    @abstractproperty
    def target_shape(self):
        pass # TODO: implement it here from self._data? But can be overriden in sub class (moving mnist)

    @property
    def size(self):
        return self._dataset_size
    
    def reset(self):
        self._row = 0
        np.random.shuffle(self._indices)

    @abstractmethod
    def get_batch(self, batch_size):
        pass
    
    
class AbstractImageDataset(AbstractDataset):
    __metaclass__ = ABCMeta

    def __init__(self, data, targets, dataset_size, image_size):
        assert len(image_size) == 3, "Image size has to have ndim=3."
        
        self._image_size = image_size
        super(AbstractImageDataset, self).__init__(data, targets, dataset_size)
    
    @property
    @tt.utils.attr.override
    def input_shape(self):
        return [self._image_size[0], self._image_size[1], self._image_size[2]]
    
    @property
    @tt.utils.attr.override
    def target_shape(self):
        return [self._image_size[0], self._image_size[1], self._image_size[2]]
    
    @property 
    def image_size(self):
        return self._image_size
    
    
class AbstractImageSequenceDataset(AbstractImageDataset):
    __metaclass__ = ABCMeta

    def __init__(self, data, dataset_size, image_size,
                 input_seq_length, target_seq_length):
        self._input_seq_length = input_seq_length
        self._target_seq_length = target_seq_length
        super(AbstractImageSequenceDataset, self).__init__(data, None, dataset_size, image_size)
    
    @property
    @tt.utils.attr.override
    def input_shape(self):
        return [self._input_seq_length] + super(AbstractImageSequenceDataset, self).input_shape
    
    @property
    @tt.utils.attr.override
    def target_shape(self):
        return [self._target_seq_length] + super(AbstractImageSequenceDataset, self).target_shape

    @property
    def input_seq_length(self):
        return self._input_seq_length
    
    @property
    def target_seq_length(self):
        return self._target_seq_length