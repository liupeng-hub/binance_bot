import backtrader as bt

class TestStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('devfactor', 2.0),
    )

print(f"Type of params: {type(TestStrategy.params)}")
print(f"Dir of params: {dir(TestStrategy.params)}")

if hasattr(TestStrategy.params, '_getitems'):
    print(f"Items: {TestStrategy.params._getitems()}")
