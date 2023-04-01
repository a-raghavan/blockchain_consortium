import blockchain as bc

s = bc.State()
s.balances['A'] = 10000
txns = [bc.Transaction('A', 'B', 2500), 
bc.Transaction('A', 'B', 3000), 
bc.Transaction('A', 'C', 550), 
bc.Transaction('A', 'C', 2800), 
bc.Transaction('A', 'B', 1000), 
bc.Transaction('A', 'C', 550)]
print([t.encode() for t in s.validate_txns(txns)])
        

