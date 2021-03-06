import os

from matplotlib.image import imread
import tensorflow as tf
import numpy as np

import dataset


# https://www.youtube.com/watch?v=oxrcZ9uUblI  funny and good tutorial on tensorflow records
def create_tfrecords(name='Cifar10', datadir=os.path.expanduser('~/Cifar10')):
    # name:  Name of dataset
    # datadir:  Directory to store data in
    # returns: tuple of train and test record paths

    # targets for efficient tensorflow record files
    train_record_path = os.path.join(datadir, 'train.tfrecord')
    test_record_path = os.path.join(datadir, 'test.tfrecord')

    # run data conversion
    if name == 'OxfordFlower':
        # get or retrieve data/paths, oxford is already jpegs
        data = dataset.Dataset(name, datadir)
        convert(
            *data.get_train_data(), train_record_path
        )
        convert(
            *data.get_test_data(), test_record_path
        )
    elif name == 'Cifar10':
        # have to get data from pregenerated batches...
        convert_from_data(
            dataset.yield_cifar_10_dataset(datadir, train=True),
            train_record_path
        )
        convert_from_data(
            dataset.yield_cifar_10_dataset(datadir, train=True),
            test_record_path
        )

    return train_record_path, test_record_path


def wrap_bytes(value):
    # converts raw image data into tf object
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def wrap_int64(value):
    # converts int to list of 1 int then to tf object
    if hasattr(value, '__iter__'):
        return tf.train.Feature(int64_list=tf.train.Int64List(value=value))
    else:
        return wrap_int64([value])


def convert(image_paths, labels, record_path):

    # Open each image and write it into TFRecord.
    with tf.python_io.TFRecordWriter(record_path) as writer:
        for path, label in zip(image_paths, labels):
            # load image data
            with open(path, 'rb') as f:
                img = imread(f)
            img = centered_crop(img, 500, 500)  # @hardcoded to 500x500 for now
            y, x, channels = img.shape

            # Convert the image to raw bytes.
            img_bytes = img.tostring()

            # decide how label must be wrapped:
            if isinstance(label, int):
                tmp = np.zeros((17,), dtype=int)
                tmp[label] = 1  # BinaryLabel array for softmax classification.
                label = tmp.tolist()
                wrap_label = wrap_int64
            elif isinstance(label, str):
                # assuming we have segmentations:
                img = imread(label)
                label = img.tostring()
                wrap_label = wrap_bytes

            # Wrap the data as Features.
            feature = tf.train.Features(feature={
                'image': wrap_bytes(img_bytes),
                'label': wrap_label(label),
                'xdim': wrap_int64(x),
                'ydim': wrap_int64(y),
                'channels': wrap_int64(channels)
            })

            example = tf.train.Example(features=feature)

            # Save current input into tfrecords file
            writer.write(example.SerializeToString())


def convert_from_data(data_getter, record_path):

    # Open each image and write it into TFRecord.
    with tf.python_io.TFRecordWriter(record_path) as writer:
        for data, label in data_getter:

            img = convert_images(data)
            num, y, x, channels = img.shape

            # Convert the image to raw bytes.
            img_bytes = img.tostring()

            # decide how label must be wrapped:
            if isinstance(label, int):
                tmp = np.zeros((10,), dtype=int)  # @hardcoded Cifar10
                tmp[label] = 1  # BinaryLabel array for softmax classification.
                label = tmp.tolist()
                wrap_label = wrap_int64
            elif isinstance(label, str):
                # assuming we have segmentations:
                img = imread(label)
                label = img.tostring()
                wrap_label = wrap_bytes

            # Wrap the data as Features.
            feature = tf.train.Features(feature={
                'image': wrap_bytes(img_bytes),
                'label': wrap_label(label),
                'xdim': wrap_int64(x),
                'ydim': wrap_int64(y),
                'channels': wrap_int64(channels)
            })

            example = tf.train.Example(features=feature)

            # Save current input into tfrecords file
            writer.write(example.SerializeToString())


def parse(serialized):
    # these are the expected features in the dataset. I may need to modify if we end up trying segmentation.
    features = \
        {
            'image': tf.FixedLenFeature([], tf.string),
            'label': tf.FixedLenFeature(17, tf.int64),
            'xdim': tf.FixedLenFeature(1, tf.int64),
            'ydim': tf.FixedLenFeature(1, tf.int64),
            'channels': tf.FixedLenFeature(1, tf.int64)
        }

    # Parse the serialized data so we get a dict with our data.
    parsed_example = tf.parse_single_example(serialized=serialized,
                                             features=features)

    # Get the image as raw bytes.
    image_raw = parsed_example['image']

    # Decode the raw bytes to float32 tensor image
    image = tf.decode_raw(image_raw, tf.float32)
    # image = tf.cast(image, tf.float32)

    # get image metadata
    label = parsed_example['label']
    xdim = parsed_example['xdim']
    ydim = parsed_example['ydim']
    channels = parsed_example['channels']

    # The image and label are now correct TensorFlow types.
    return image, label, xdim, ydim, channels


def input_fn(filenames, train=True, batch_size=32, buffer_size=512):
    # Args:
    # filenames:   Filenames for the TFRecords files.
    # train:       Boolean whether training (True) or testing (False).
    # batch_size:  Return batches of this size.
    # buffer_size: Read buffers of this size. The random shuffling
    #              is done on the buffer, so it must be big enough.

    # Create a TensorFlow Dataset-object which has functionality
    # for reading and shuffling data from TFRecords files.
    dataset = tf.data.TFRecordDataset(filenames=filenames)

    # Parse the serialized data in the TFRecords files.
    # This returns TensorFlow tensors for the image and labels.
    dataset = dataset.map(parse)

    if train:
        # If training then read a buffer of the given size and
        # randomly shuffle it.
        dataset = dataset.shuffle(buffer_size=buffer_size)

        # Allow infinite reading of the data.
        num_repeat = None
    else:
        # If testing then don't shuffle the data.
        num_repeat = 1

    # Repeat the dataset the given number of times.
    dataset = dataset.repeat(num_repeat)

    # Get a batch of data with the given size.
    dataset = dataset.batch(batch_size)

    # Create an iterator for the dataset and the above modifications.
    iterator = dataset.make_one_shot_iterator()

    # Get the next batch of images and labels, may take dimensionality info later but for now we set to _
    images_batch, labels_batch, \
        xdim_batch, ydim_batch, channels_batch = iterator.get_next()

    if train:
        images_batch = distort_batch(images_batch)

    # The input-function must return a dict wrapping the images.
    x = {'x': images_batch}
    y = labels_batch

    return x, y


def train_input_fn():
    # @hardcoded Cifar10
    return input_fn(os.path.expanduser('~/OxfordFlower/train.tfrecord'))


def test_input_fn():
    # testing set size...
    return input_fn(os.path.expanduser('~/OxfordFlower/test.tfrecord'), train=False)


# basic helpers
def centered_crop(img, xdim, ydim):
    # dataset needs to be of the same shape, this is the early, simple solution.
    y, x, _ = img.shape
    if y < 500:
        # some images are Nx499 :(  Padding in with zeros for those images.
        img = np.vstack((img, 0 * img[0, :][np.newaxis, :]))
        y, x, _ = img.shape
    if x < 500:
        img = np.hstack((img, 0 * img[:, 0][:, np.newaxis]))
        y, x, _ = img.shape

    x0 = x//2-(xdim // 2)
    y0 = y//2-(ydim // 2)
    return img[y0:y0 + ydim, x0:x0 + xdim, :]


def convert_images(raw):
    """
    Convert images from the CIFAR-10 format and
    return a 4-dim array with shape: [image_number, height, width, channel]
    where the pixels are floats between 0.0 and 1.0.
    """

    # Convert the raw images from the data-files to floating-points.
    raw_float = np.array(raw, dtype=np.float32) / 255.0

    # Reshape the array to 4-dimensions.
    images = raw_float.reshape([-1, 3, 32, 32])

    # Reorder the indices of the array.
    images = images.transpose([0, 2, 3, 1])

    return images


def distort(img: tf.Tensor) -> tf.Tensor:
    img = tf.image.random_hue(img, max_delta=0.05)
    img = tf.image.random_contrast(img, lower=0.3, upper=1.0)
    img = tf.image.random_saturation(img, lower=0.0, upper=2.0)
    img = tf.image.random_flip_left_right(img)
    return img


def distort_batch(image_batch: tf.Tensor) -> tf.Tensor:
    shape = [-1, 500, 500, 3]  # @hardcoded Cifar10
    image_batch = tf.reshape(image_batch, shape=shape)
    image_batch = tf.map_fn(lambda img: distort(img), image_batch)
    image_batch = tf.reshape(image_batch, shape=[-1, np.product(shape[1:])])

    return image_batch


if __name__ == '__main__':
    create_tfrecords()
