from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import pandas as pd

from .transforms import Transform, grid
from .types import Vector


class Marginal1D(ABC):
    def mean(self) -> float:
        """Expected value at a time horizon"""
        return self.mean_from_characteristic()

    def std(self) -> float:
        """Standard deviation at a time horizon"""
        return np.sqrt(self.variance())

    def variance(self) -> float:
        """Variance at a time horizon"""
        return self.variance_from_characteristic()

    def mean_from_characteristic(self) -> float:
        """Calculate mean as first derivative of characteristic function at 0"""
        d = 0.001
        m = -0.5 * 1j * (self.characteristic(d) - self.characteristic(-d)) / d
        return m.real

    def variance_from_characteristic(self) -> float:
        """Calculate variance as second derivative of characteristic function at 0"""
        d = 0.001
        c1 = self.characteristic(d)
        c0 = self.characteristic(0)
        c2 = self.characteristic(-d)
        m = -0.5 * 1j * (c1 - c2) / d
        s = -(c1 - 2 * c0 + c2) / (d * d) - m * m
        return s.real

    def pdf(self, n: Vector) -> Vector:
        """
        Computes the probability density (or mass) function of the process.

        It has a base implementation that computes the pdf from the
        :class:`cdf` method, but a subclass should overload this method if a
        more optimized way of computing it is available.

        :param t: time horizon
        :param n: Location in the stochastic process domain space. If a numpy array,
            the output should have the same shape as the input.
        """
        return self.cdf(n) - self.cdf(n - 1)

    def frequency_space(self, N: int, max_frequency: float = 10.0) -> np.ndarray:
        return max_frequency * grid(N) / N

    def pdf_from_characteristic(
        self,
        N: int,
        max_frequency: float = 10.0,
        delta_x: Optional[float] = None,
        simpson_rule: bool = False,
    ) -> np.ndarray:
        t = Transform(N, max_frequency, simpson_rule)
        return pd.DataFrame(t(self.characteristic(t.freq), delta_x))

    def call_option(
        self,
        N: int,
        max_frequency: float = 10.0,
        delta_x: Optional[float] = None,
        alpha: float = 0.5,
        simpson_rule: bool = False,
    ):
        t = Transform(N, max_frequency, simpson_rule)
        phi = self.call_option_transform(t.freq - 1j * alpha)
        result = t(phi, delta_x)
        x = result["x"]
        y = result["y"]
        return pd.DataFrame(dict(x=x, y=y * np.exp(-alpha * x)))

    def call_option_transform(self, u: Vector) -> Vector:
        """Call option transfrom"""
        uj = 1j * u
        return self.characteristic_corrected(u - 1j) / (uj * uj + uj)

    def characteristic_corrected(self, u: Vector) -> Vector:
        convexity = np.log(self.characteristic(-1j))
        return self.characteristic(u) * np.exp(-1j * u * convexity)

    @abstractmethod
    def cdf(self, n: Vector) -> Vector:
        """
        Compute the cumulative distribution function of the process.

        :param t: time horizon
        :param n: Location in the stochastic process domain space. If a numpy array,
            the output should have the same shape as the input.
        """

    @abstractmethod
    def characteristic(self, n: Vector) -> Vector:
        """
        Compute the characteristic function on support points `n`.
        """
