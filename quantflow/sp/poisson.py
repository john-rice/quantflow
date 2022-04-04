from typing import List, Tuple

import numpy as np
from scipy.stats import poisson, skellam

from ..utils.functions import factorial
from ..utils.param import Param, Parameters
from ..utils.types import Vector
from .base import CountingProcess1D, CountingProcess2D, Im


class PoissonProcess(CountingProcess1D):
    r"""
    THe 1D Poisson process is one of the most common Levy processes.

    It's point process where the inter-arrival time is exponentially distributed
    with rate $\lambda$
    """

    def __init__(self, rate: float) -> None:
        self.rate = Param(
            "lambda", rate, bounds=(0, None), description="intensity rate"
        )

    def __repr__(self):
        return f"{self.__class__.__name__} {self.rate}"

    @property
    def parameters(self) -> Parameters:
        return Parameters(self.rate)

    def pdf(self, t: float, n: Vector = 0) -> Vector:
        r"""
        Probability density function of the number of events at time ``t``.

        It's given by

        \begin{equation}
            f_{X}\left(n\right)=\frac{\lambda^{n}e^{-\lambda}}{n!}
        \end{equation}
        """
        return poisson.pmf(n, t * self.rate.value)

    def cdf(self, t: float, n: Vector) -> Vector:
        r"""
        CDF of the number of events at time ``t``.

        It's given by

        .. math::
            :label: poisson_cdf

            F_{X}\left(n\right)=\frac{\Gamma\left(\left\lfloor n+1\right\rfloor
            ,\lambda\right)}{\left\lfloor n\right\rfloor !}

        where :math:`\Gamma` is the upper incomplete gamma function.
        """
        return poisson.cdf(n, t * self.rate.value)

    def cdf_jacobian(self, t: float, n: Vector) -> np.ndarray:
        r"""
        Jacobian of the CDF

        It's given by

        .. math::

            \frac{\partial F}{\partial\lambda}=-\frac{\lambda^{\left\lfloor
            n\right\rfloor }e^{-\lambda}}{\left\lfloor n\right\rfloor !}
        """
        k = np.floor(n).astype(int)
        rate = self.rate.value
        return np.array([-(rate**k) * np.exp(-rate)]) / factorial(k)

    def characteristic_exponent(self, u: Vector) -> Vector:
        return self.rate.value * (np.exp(Im * u) - 1)

    def characteristic(self, t: float, u: Vector) -> Vector:
        return np.exp(t * self.characteristic_exponent(u))

    def sample(self, n: int, t: float = 1, steps: int = 0) -> np.array:
        size, dt = self.sample_dt(t, steps)
        paths = np.zeros((size + 1, n))
        for p in range(n):
            arrivals = self.arrivals(t)
            if arrivals:
                jumps = self.jumps(len(arrivals))
                i = 1
                y = 0.0
                for j, arrival in enumerate(arrivals):
                    while i * dt < arrival:
                        paths[i, p] = y
                        i += 1
                    y += jumps[j]
                paths[i:, p] = y
        return paths

    def arrivals(self, t: float = 1) -> List[float]:
        """Generate a list of jump arrivals times up to time t"""
        exp_rate = 1.0 / self.rate.value
        arrivals = []
        tt = 0
        while tt <= t:
            arrivals.append(tt)
            dt = np.random.exponential(scale=exp_rate)
            tt += dt
        return arrivals

    def jumps(self, n: int) -> np.array:
        return np.ones((n,))


class SkellamProcess(CountingProcess1D):
    """
    Process resulting from the difference of two uncorrelated Poisson random
    variables.

    .. attribute:: rate_left
    .. attribute:: rate_right

        The arrival rate of events for each of the poisson processes.
        Must be positive.
    """

    def __init__(self, rate_left: float, rate_right: float) -> None:
        self.rate_left = rate_left
        self.rate_right = rate_right

    def cdf(self, t: float, n: Vector = 0) -> Vector:
        r"""
        PDF of the number of events at time ``t``.

        It's given by

        .. math::

            f_{X}\left(n\right)=e^{-(\lambda_{1}+\lambda_{2})}\left(
            \frac{\lambda_{1}}{\lambda_{2}}\right)^{n/2}I_{|n|}(
            2\sqrt{\lambda_{1}\lambda_{2}})

        where ``I`` is the modified Bessel function of the first kind.
        """
        return skellam.cdf(n, t * self.rate_left, t * self.rate_right)

    def pdf(self, t: float, n: Vector = 0) -> Vector:
        r"""
        CDF of the number of events at time ``t``.

        Couldn't find the closed form of this, but it's similar to the CDF of
        the non-central chi-squared distribution, which computed in terms
        of the Marcum Q-function.
        """
        return skellam.pmf(n, t * self.rate_left, t * self.rate_right)

    def sample(self, n: int, t: float = 1, steps: int = 0) -> np.array:
        raise NotImplementedError


class DoubleIndependentPoisson(CountingProcess2D):
    """
    2D Process where each of the random variables are uncorrelated poisson processes.

    This is an optimized implementation equivalent to::

        combined.CombinedStochasticProcess(
            poisson.PoissonProcess(rate1),
            poisson.PoissonProcess(rate2),
            copula.IndependentCopula(),
        )

    .. attribute:: rate_left
    .. attribute:: rate_right

        The arrival rate of each of the marginal processes.
    """

    def __init__(self, rate_left: float, rate_right: float):
        self.rate_left = rate_left
        self.rate_right = rate_right

    def pdf(self, t: float, n: Tuple[Vector, Vector]) -> Vector:
        """
        PDF of the process. It's just the product of two
        poisson pdfs :eq:`poisson_pdf`.
        """
        return poisson._pmf(n[0], t * self.rate_left) * poisson._pmf(
            n[1], t * self.rate_right
        )

    def cdf(self, t: float, n: Tuple[Vector, Vector]) -> Vector:
        """
        CDF of the process. It's just the product of two
        poisson cdfs :eq:`poisson_cdf`.
        """
        return poisson._cdf(n[0], t * self.rate_left) * poisson._cdf(
            n[1], t * self.rate_right
        )

    def marginals(self) -> Tuple[CountingProcess1D, CountingProcess1D]:
        """
        Returns the marginal poisson processes of each of the two random variables
        """
        return PoissonProcess(self.rate_left), PoissonProcess(self.rate_right)

    def sum_process(self) -> CountingProcess1D:
        """
        The sum process, which is just a :class:`PoissonProcess` with
        rate ``rate_left + rate_right``.
        """
        return PoissonProcess(self.rate_left + self.rate_right)

    def difference_process(self) -> CountingProcess1D:
        """
        The difference process, which is just a :class:`SkellamProcess` with
        rates ``rate_left`` and ``rate_right``.
        """
        return SkellamProcess(self.rate_left, self.rate_right)

    def sample(self, n: int, t: float = 1, steps: int = 0) -> np.array:
        """require implementation"""
        raise NotImplementedError
