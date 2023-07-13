import pytest

from quantflow.sp.bns import BNS
from quantflow.sp.ou import GammaOU


@pytest.fixture
def gamma_ou() -> GammaOU:
    return GammaOU.create(decay=10, kappa=5)


@pytest.fixture
def bns() -> BNS:
    return BNS.create(vol=0.5, decay=5, kappa=1, rho=0)


def test_marginal(gamma_ou: GammaOU) -> None:
    m = gamma_ou.marginal(1)
    assert m.mean() == 1


def test_sample(gamma_ou: GammaOU) -> None:
    paths = gamma_ou.sample(10, 1, 100)
    assert paths.t == 1
    assert paths.dt == 0.01


def test_bns(bns: BNS):
    m = bns.marginal(1)
    assert bns.characteristic(1, 0) == 1
    assert m.mean() == 0.0
    # assert pytest.approx(m.std(), 1e-3) == 0.5