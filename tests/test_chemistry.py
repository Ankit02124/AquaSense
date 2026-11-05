import math

import pytest

import chemistry as chem


class TestSalinity:
    def test_pss78_reference_point(self):
        # By definition: C(35, 15 degC, 0) = 42.914 mS/cm  ->  S = 35
        assert chem.salinity_pss78(42.914, 15.0) == pytest.approx(35.0, abs=1e-3)

    def test_pss78_standard_seawater_at_25c(self):
        assert chem.salinity_pss78(53.065, 25.0) == pytest.approx(35.0, abs=0.02)

    def test_freshwater_is_small_and_positive(self):
        s = chem.salinity_pss78(0.5, 25.0)
        assert 0.15 < s < 0.35

    def test_monotonic_in_conductivity(self):
        values = [chem.salinity_pss78(ec, 28.0) for ec in (0.2, 1, 5, 20, 45)]
        assert values == sorted(values)

    def test_zero_conductivity(self):
        assert chem.salinity_pss78(0.0, 25.0) == 0.0


class TestDissolvedOxygen:
    @pytest.mark.parametrize("temp, expected", [(0, 14.62), (20, 9.09), (25, 8.26), (30, 7.56)])
    def test_saturation_freshwater(self, temp, expected):
        # APHA 4500-O table values (fresh water, 1 atm)
        assert chem.do_saturation_mg_l(temp) == pytest.approx(expected, abs=0.03)

    def test_salinity_lowers_solubility(self):
        fresh, sea = chem.do_saturation_mg_l(25), chem.do_saturation_mg_l(25, 35)
        assert 6.6 < sea < 6.9 and sea < fresh

    def test_altitude_lowers_solubility(self):
        p = chem.pressure_from_altitude_kpa(1000)
        assert p == pytest.approx(89.87, abs=0.1)
        ratio = chem.do_saturation_mg_l(25, 0, p) / chem.do_saturation_mg_l(25)
        assert ratio == pytest.approx(0.885, abs=0.01)

    def test_probe_conversion_at_calibration_point_is_100_percent(self):
        cal = chem.DoCalibration(cal1_mv=1600, cal1_temp_c=25)
        assert chem.do_percent_saturation(1600, 25, cal) == pytest.approx(100.0)
        assert chem.do_mg_l_from_mv(1600, 25, cal) == pytest.approx(chem.do_saturation_mg_l(25))
        assert chem.do_mg_l_from_mv(800, 25, cal) == pytest.approx(chem.do_saturation_mg_l(25) / 2)

    def test_two_point_interpolation(self):
        cal = chem.DoCalibration(mode="two_point", cal1_mv=1600, cal1_temp_c=25, cal2_mv=1300, cal2_temp_c=15)
        assert chem.do_saturation_voltage_mv(20, cal) == pytest.approx(1450)


class TestPh:
    def test_two_point(self):
        cal = chem.PhCalibration()
        assert chem.ph_from_mv(cal.v_neutral_mv, cal) == pytest.approx(7.0)
        assert chem.ph_from_mv(cal.v_acid_mv, cal) == pytest.approx(4.0)

    def test_nernst_temperature_compensation(self):
        cal = chem.PhCalibration()
        mv = cal.v_acid_mv  # pH 4 at 25 C
        # Same voltage at a warmer temperature means a slightly smaller pH deviation
        warm = chem.ph_from_mv(mv, cal, temp_c=35)
        assert 4.0 < warm < 4.15
        assert chem.ph_from_mv(cal.v_neutral_mv, cal, temp_c=35) == pytest.approx(7.0)

    def test_identical_calibration_points_rejected(self):
        with pytest.raises(ValueError):
            chem.ph_from_mv(1500, chem.PhCalibration(1500, 1500))


class TestOther:
    def test_ec_board_transfer(self):
        cal = chem.EcCalibration()
        assert chem.ec_at_temp_from_mv(1000, cal) == pytest.approx(1000 * 1000 / 820 / 200)

    def test_ec_temperature_compensation(self):
        assert chem.ec25_from_ec(1.0185, 26.0) == pytest.approx(1.0)

    def test_turbidity_curve(self):
        cal = chem.TurbidityCalibration(divider_ratio=1.5, clear_water_v=4.2)
        assert chem.turbidity_ntu_from_mv(4200 / 1.5, cal) == 0.0
        assert chem.turbidity_ntu_from_mv(3000 / 1.5, cal) == pytest.approx(2789.5, abs=0.5)
        assert chem.turbidity_ntu_from_mv(1000, cal) == 3000.0
        for ntu in (5, 50, 500):
            mv = chem.turbidity_pin_mv_from_ntu(ntu, cal)
            assert chem.turbidity_ntu_from_mv(mv, cal) == pytest.approx(ntu, abs=1e-6)

    def test_unionised_ammonia_fraction(self):
        assert chem.nh3_fraction(8.0, 25.0) == pytest.approx(0.0537, abs=0.002)
        assert chem.nh3_fraction(9.0, 30.0) > chem.nh3_fraction(8.0, 30.0)

    def test_all_outputs_finite(self):
        for t in (5, 15, 25, 35):
            assert math.isfinite(chem.do_saturation_mg_l(t, 20))
