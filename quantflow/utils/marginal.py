from abc import ABC, abstractmethod
from typing import Any, Optional, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel
from scipy.optimize import Bounds

from .transforms import Transform, TransformResult, default_bounds
from .types import FloatArray, Vector


class Marginal1D(BaseModel, ABC):
    """Marginal distribution"""

    @abstractmethod
    def characteristic(self, u: Vector) -> Vector:
        """
        Compute the characteristic function on support points `n`.
        """

    def mean(self) -> Vector:
        """Expected value

        THis should be overloaded if a more efficient way of computing the mean
        """
        return self.mean_from_characteristic()

    def variance(self) -> Vector:
        """Variance

        This should be overloaded if a more efficient way of computing the
        """
        return self.variance_from_characteristic()

    def max_frequency(self) -> float:
        """Maximum frequency of the characteristic function

        This should be overloaded if required
        """
        return 20

    def std(self) -> Vector:
        """Standard deviation at a time horizon"""
        return np.sqrt(self.variance())

    def mean_from_characteristic(self) -> Vector:
        """Calculate mean as first derivative of characteristic function at 0"""
        d = 0.001
        m = -0.5 * 1j * (self.characteristic(d) - self.characteristic(-d)) / d
        return cast(complex, m).real

    def variance_from_characteristic(self) -> Vector:
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

        :param n: Location in the stochastic process domain space. If a numpy array,
            the output should have the same shape as the input.
        """
        return self.cdf(n) - self.cdf(n - 1)

    def pdf_from_characteristic(
        self,
        n_or_x: int | FloatArray | None = None,
        max_frequency: float | None = None,
        delta_x: float | None = None,
        simpson_rule: bool = False,
    ) -> TransformResult:
        """
        Compute the probability density function from the characteristic function.
        """
        n = None
        if isinstance(n_or_x, int):
            n = n_or_x
        elif n_or_x is not None and delta_x is None:
            min_x = float(np.min(n_or_x))
            max_x = float(np.max(n_or_x))
            delta_x = (max_x - min_x) / (len(n_or_x) - 1)
        transform = Transform(
            n,
            max_frequency=self.get_max_frequency(max_frequency),
            domain_range=self.domain_range(),
            simpson_rule=simpson_rule,
        )
        psi = cast(np.ndarray, self.characteristic(transform.frequency_domain))
        return transform(psi, delta_x)

    def call_option(
        self,
        N: int,
        max_frequency: float = 10.0,
        delta_x: Optional[float] = None,
        alpha: float = 0.5,
        simpson_rule: bool = False,
    ) -> TransformResult:
        t = Transform(
            N,
            max_frequency=self.get_max_frequency(max_frequency),
            domain_range=self.domain_range(),
            simpson_rule=simpson_rule,
        )
        phi = cast(
            np.ndarray, self.call_option_transform(t.frequency_domain - 1j * alpha)
        )
        result = t(phi, delta_x)
        return TransformResult(x=result.x, y=result.y * np.exp(-alpha * result.x))

    def call_option_transform(self, u: Vector) -> Vector:
        """Call option transfrom"""
        uj = 1j * u
        return self.characteristic_corrected(u - 1j) / (uj * uj + uj)

    def characteristic_corrected(self, u: Vector) -> Vector:
        convexity = np.log(self.characteristic(-1j))
        return self.characteristic(u) * np.exp(-1j * u * convexity)

    def domain_range(self) -> Bounds:
        return default_bounds()

    def cdf(self, n: Vector) -> Vector:
        """
        Compute the cumulative distribution function

        :param n: Location in the stochastic process domain space. If a numpy array,
            the output should have the same shape as the input.
        """
        raise NotImplementedError("Analytical CFD not available")

    def pdf_jacobian(self, n: Vector) -> np.ndarray:
        """
        Jacobian of the pdf with respect to the parameters of the process.
        It has a base implementation that computes it from the
        :class:`cdf_jacobian` method, but a subclass should overload this method if a
        more optimized way of computing it is available.
        """
        return self.cdf_jacobian(n) - self.cdf_jacobian(n - 1)

    def cdf_jacobian(self, n: Vector) -> np.ndarray:
        """
        Jacobian of the cdf with respect to the parameters of the process.
        It is useful for optimization purposes if necessary.

        Optional to implement, otherwise raises ``NotImplementedError`` if called.
        """
        raise NotImplementedError("Analytical CFD Jacobian not available")

    def characteristic_df(
        self, n: int | None, max_frequency: float | None = None, **kwargs: Any
    ) -> pd.DataFrame:
        """
        Compute the characteristic function with n discretization points
        and a max frequency
        """
        fre = Transform(
            n=n, max_frequency=self.get_max_frequency(max_frequency), **kwargs
        ).frequency_domain
        psi = self.characteristic(fre)
        return pd.concat(
            (
                pd.DataFrame(dict(frequency=fre, characteristic=psi.real, name="real")),
                pd.DataFrame(dict(frequency=fre, characteristic=psi.imag, name="iamg")),
            )
        )

    def get_max_frequency(self, max_frequency: float | None = None) -> float:
        """
        Get the maximum frequency to use for the characteristic function
        """
        return max_frequency if max_frequency is not None else self.max_frequency()
