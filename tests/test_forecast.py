import pytest
from dewbot.dice import point_advantage

@pytest.mark.parametrize("defense,attack,probability,tier", [
    ("1","5",0,0),("1d6","6",1/6,0),("1d6","5",2/6,1),
    ("1d6","4",.5,2),("1d6","3",4/6,3),("1d6","2",5/6,4),
    ("5","5",1,4),("-1","0",0,0),("1d5","5",.2,1),
    ("1d5","2",.8,3), ("1d6","1d6",21/36,2),
])
def test_exact_point_forecasts(defense,attack,probability,tier):
    value=point_advantage(defense,attack)
    assert value['probability']==pytest.approx(probability,abs=1e-6)
    assert value['tier']==tier
    assert not value['approximate']


def test_paralysis_changes_attack_points():
    assert point_advantage('3','1d6+3',1)['probability']==1
    assert point_advantage('3','1d6+3')['probability']==0
