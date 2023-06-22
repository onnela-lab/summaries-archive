import itertools as it
import logging
import numpy as np
from scipy import spatial
from sklearn import linear_model, preprocessing
from tqdm import tqdm
import typing
from .util import estimate_entropy


class Algorithm:
    """
    Abstract interface for inference algorithms.
    """
    def sample(self, data: np.ndarray, num_samples: int, show_progress: bool = True, **kwargs) \
            -> typing.Tuple[np.ndarray, dict]:
        """
        Draw posterior samples given the observed data.

        Args:
            data: Data array with shape `(n, p)`, where `n` is the number of independent
                observations and `p` is the number of data points per observation.
            num_samples: Number of posterior samples to draw per observation.
            show_progress: Show a tqdm progressbar if `True`.

        Returns:
            samples: Array of posterior samples with shape `(n, q)`, where `q` is the number of
                parameters.
            info: Dictionary of auxiliary information generated by sampling the posterior.
        """
        raise NotImplementedError

    @property
    def num_params(self):
        """
        Number of parameters of the model.
        """
        raise NotImplementedError

    @property
    def logger(self):
        """
        Algorithm-specific logger.
        """
        return logging.getLogger(self.__class__.__name__)


class CompressorMixin:
    """
    Interface for compressing data.
    """
    def get_compressor(self, data: np.ndarray) -> typing.Callable:
        """
        Obtain a possibly data-dependent compression function.

        Args:
            data: Data vector with length `p` equal to the number of data points per observation.

        Returns:
            compressor: Function to compress data with `p` features.
        """
        raise NotImplementedError


class ABCAlgorithm(Algorithm):
    """
    Abstract interface for inference algorithms based on approximate Bayesian computation.

    Args:
        train_data: Reference table of simulated data with shape `(n, p)`, where `n` is the
            number of simulations and `p` is the number of features.
        train_params: Reference table of simulated parameter values with shape `(n, q)`, where `n`
            is the number of simulatiosn and `q` is the number of parameters.
        standardize: Standardize the features.
    """
    def __init__(self, train_data: np.ndarray, train_params: np.ndarray, standardize: bool = True):
        self.train_data = np.asarray(train_data)
        assert self.train_data.ndim == 2, 'expected features to have two dimensions but got ' \
            f'shape {self.train_data.shape}'

        self.train_params = np.asarray(train_params)
        assert self.train_params.ndim == 2, 'expected parameters to have two dimensions but got ' \
            f'shape {self.train_params.shape}'

        assert self.train_data.shape[0] == self.train_params.shape[0]

        if standardize:
            self.standard_scalar = preprocessing.StandardScaler()
            self.train_data = self.standard_scalar.fit_transform(self.train_data)
        else:
            self.standard_scalar = None

    @property
    def num_params(self):
        return self.train_params.shape[1]


class NearestNeighborAlgorithm(ABCAlgorithm):
    """
    Nearest neighbor sampling algorithm based on the Euclidean distance between features.

    Args:
        train_data: Reference table of simulated data with shape `(n, p)`, where `n` is the
            number of simulations and `p` is the number of features.
        train_params: Reference table of simulated parameter values with shape `(n, q)`, where `n`
            is the number of simulations and `q` is the number of parameters.
    """
    def __init__(self, train_data: np.ndarray, train_params: np.ndarray, standardize: bool = True):
        super().__init__(train_data, train_params, standardize)
        self.reference = spatial.KDTree(self.train_data)

    def sample(self, data: np.ndarray, num_samples: int, show_progress: bool = True, **kwargs) \
            -> typing.Tuple[np.ndarray, dict]:
        """
        Draw samples from the parameter reference table that minimize the Euclidean distance between
        the corresponding data in the reference table and the observed data.

        Args:
            data: Data array with shape `(n, p)`, where `n` is the number of independent
                observations and `p` is the number of data points per observation.
            num_samples: Number of posterior samples to draw per observation.
            show_progress: Ignored by this algorithm.

        Returns:
            samples: Array of posterior samples with shape `(n, q)`, where `q` is the number of
                parameters.
            info: Dictionary of auxiliary information generated by sampling the posterior.
        """
        data = np.atleast_2d(data)
        if self.standard_scalar:
            data = self.standard_scalar.transform(data)
        distances, indices = self.reference.query(data, k=num_samples, **kwargs)
        y = self.train_params[indices]
        return y, {'indices': indices, 'distances': distances}


class SubsetSelectionAlgorithm(ABCAlgorithm, CompressorMixin):
    """
    Base class for algorithms that select discrete subsets of candidate features.
    """
    def sample(self, data: np.ndarray, num_samples: int, show_progress: bool = True, **kwargs) \
            -> typing.Tuple[np.ndarray, dict]:
        if self.standard_scalar:
            data = self.standard_scalar.transform(data)
        best_loss = None
        best_samples = None
        best_mask = None
        num_features = self.train_data.shape[1]
        masks = np.asarray([mask for mask in it.product(*[(False, True)] * num_features)
                            if any(mask)])
        losses = []
        for mask in tqdm(masks) if show_progress else masks:
            # Construct a child nearest neighbor algorithm and draw posterior samples. Do not
            # standardize for the child ABC algorithm because we may have already applied a
            # standardization.
            train_data_subset = self.train_data[:, mask]
            child = NearestNeighborAlgorithm(train_data_subset, self.train_params,
                                             standardize=False)
            data_subset = data[:, mask]
            samples, _ = child.sample(data_subset, num_samples, **kwargs)

            # Evaluate the loss and select the best subset for each sample.
            loss = self.evaluate_loss(samples)
            losses.append(loss)
            if best_loss is None:
                best_loss = loss
                best_samples = samples
                best_mask = np.repeat([mask], data.shape[0], axis=0)
            else:
                idx, = np.where(loss < best_loss)
                best_samples[idx] = samples[idx]
                best_mask[idx] = mask
                best_loss = np.minimum(best_loss, loss)

        return best_samples, {
            'best_mask': best_mask,
            'best_loss': best_loss,
            'masks': masks,
            'losses': np.asarray(losses),
        }

    def evaluate_loss(self, samples: np.ndarray) -> np.ndarray:
        """
        Evaluate a loss function for the candidate posterior samples.

        Args:
            samples: Array of posterior samples with shape `(n, q)`, where `q` is the number of
                parameters.

        Returns:
            loss: Vector of loss values with length `n`.
        """
        raise NotImplementedError

    def get_compressor(self, data: np.ndarray) -> typing.Callable:
        raise NotImplementedError(
            'selecting a feature subset requires the construction of many spatial trees and is '
            'implemented as part of sampling; see `best_mask` in the auxiliary information'
        )


class NunesAlgorithm(SubsetSelectionAlgorithm):
    """
    Feature subset selection algorithm that minimizes the posterior entropy.
    """
    def evaluate_loss(self, samples):
        # Estimate the entropy independently for each element in the batch.
        return np.asarray([estimate_entropy(x) for x in samples])


class StaticCompressorNearestNeighborAlgorithm(NearestNeighborAlgorithm, CompressorMixin):
    """
    Nearest neighbor sampling algorithm with a static compressor.
    """
    def __init__(self, train_data: np.ndarray, train_params: np.ndarray,
                 compressor: typing.Callable, standardize: bool = True) -> None:
        # Compress the training data.
        self.compressor = compressor
        self._raw_train_data = train_data
        super().__init__(compressor(train_data), train_params, standardize)

    def sample(self, data: np.ndarray, num_samples: int, show_progress: bool = True, **kwargs) \
            -> typing.Tuple[np.ndarray, dict]:
        # Project into the feature space, then run as usual.
        data = self.get_compressor(None)(data)
        if self.standard_scalar:
            data = self.standard_scalar.transform(data)
        samples, info = super().sample(data, num_samples, show_progress, **kwargs)
        info['compressed_data'] = data
        return samples, info

    def get_compressor(self, data: np.ndarray) -> typing.Callable:
        assert data is None, 'data should be none for static compressors'
        return self.compressor


class FearnheadAlgorithm(StaticCompressorNearestNeighborAlgorithm):
    """
    Projection algorithm minimising the L2 loss on the training data.
    """
    def __init__(self, train_data: np.ndarray, train_params: np.ndarray, standardize: bool = False,
                 **kwargs) -> None:
        self.predictor = linear_model.LinearRegression(**kwargs)
        self.predictor.fit(train_data, train_params)
        super().__init__(train_data, train_params, self.predictor.predict, standardize)
