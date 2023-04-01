# forked from https://github.com/dvf/blockchain

import hashlib
import json
import time
import threading
import logging

import requests
from flask import Flask, request

class Transaction(object):
    def __init__(self, sender, recipient, amount):
        self.sender = sender # constraint: should exist in state
        self.recipient = recipient # constraint: need not exist in state. Should exist in state if transaction is applied.
        self.amount = amount # constraint: sender should have enough balance to send this amount

    def __str__(self) -> str:
        return "T(%s -> %s: %s)" % (self.sender, self.recipient, self.amount)

    def encode(self) -> str:
        return self.__dict__.copy()

    @staticmethod
    def decode(data):
        return Transaction(data['sender'], data['recipient'], data['amount'])

    def __lt__(self, other):
        if self.sender < other.sender: return True
        if self.sender > other.sender: return False
        if self.recipient < other.recipient: return True
        if self.recipient > other.recipient: return False
        if self.amount < other.amount: return True
        return False
    
    def __eq__(self, other) -> bool:
        return self.sender == other.sender and self.recipient == other.recipient and self.amount == other.amount

class Block(object):
    def __init__(self, number, transactions, previous_hash, miner):
        self.number = number # constraint: should be 1 larger than the previous block
        self.transactions = transactions # constraint: list of transactions. Ordering matters. They will be applied sequentlally.
        self.previous_hash = previous_hash # constraint: Should match the previous mined block's hash
        self.miner = miner # constraint: The node_identifier of the miner who mined this block
        self.hash = self._hash()

    def _hash(self):
        return hashlib.sha256(
            str(self.number).encode('utf-8') +
            str([str(txn) for txn in self.transactions]).encode('utf-8') +
            str(self.previous_hash).encode('utf-8') +
            str(self.miner).encode('utf-8')
        ).hexdigest()

    def __str__(self) -> str:
        return "B(#%s, %s, %s, %s, %s)" % (self.hash[:5], self.number, self.transactions, self.previous_hash, self.miner)
    
    def encode(self):
        encoded = self.__dict__.copy()
        encoded['transactions'] = [t.encode() for t in self.transactions]
        return encoded
    
    @staticmethod
    def decode(data):
        txns = [Transaction.decode(t) for t in data['transactions']]
        return Block(data['number'], txns, data['previous_hash'], data['miner'])

class State(object):
    def __init__(self):
        # TODO: You might want to think how you will store balance per person. DONE
        # You don't need to worry about persisting to disk. Storing in memory is fine.
        self.balances = {}          # account_id (str) -> balance (int)
        self.updates = {}

    def encode(self):
        dumped = self.balances
        # TODO: Add all person -> balance pairs into `dumped`. DONE
        return dumped

    def valid(self, transaction, temp_state):
        # TODO: check if transaction is valid against current state DONE
        if transaction.sender not in temp_state:
            return False
        if transaction.amount < 0:
            return False
        if temp_state[transaction.sender] < transaction.amount:
            return False
        
        temp_state[transaction.recipient] = temp_state.get(transaction.recipient, 0) + transaction.amount
        temp_state[transaction.sender] -= transaction.amount

        return True

    def validate_txns(self, txns):
        # TODO: returns a list of valid transactions. DONE
        # You receive a list of transactions, and you try applying them to the state.
        # If a transaction can be applied, add it to result. (should be included)
        from copy import deepcopy
        temp_state = deepcopy(self.balances)

        result = [t for t in txns if self.valid(t, temp_state)]
        return result

    def apply_transaction(self, txn):
        # apply transaction to state
        self.balances[txn.recipient] = self.balances.get(txn.recipient, 0) + txn.amount
        self.balances[txn.sender] -= txn.amount

    def update_history(self, txn, blocknum):
        if txn.sender not in self.updates:
            self.updates[txn.sender] = [[blocknum, -txn.amount]]
        else:
            if self.updates[txn.sender][-1][0] == blocknum:
                self.updates[txn.sender][-1][1] -= txn.amount
            else:
                self.updates[txn.sender].append([blocknum, -txn.amount])
        
        if txn.recipient not in self.updates:
            self.updates[txn.recipient] = [[blocknum, txn.amount]]
        else:
            if self.updates[txn.recipient][-1][0] == blocknum:
                self.updates[txn.recipient][-1][1] += txn.amount
            else:
                self.updates[txn.recipient].append([blocknum, txn.amount])

    def apply_block(self, block):
        # TODO: apply the block to the state. DONE
        for t in block.transactions:
            self.update_history(t, block.number)
            self.apply_transaction(t)
        logging.info("Block (#%s) applied to state. %d transactions applied" % (block.hash, len(block.transactions)))
        
    def history(self, account):
        # TODO: return a list of (blockNumber, value changes) that this account went through 
        # Here is an example

        # blockNumber = 3
        # amount = 200

        # blockNumber2 = 10
        # amount2 = -25

        # return [(blockNumber, amount), (blockNumber2, amount2)]
        if account not in self.updates:
            return []
        return self.updates[account]

class Blockchain(object):
    def __init__(self):
        self.nodes = []
        self.node_identifier = 0
        self.block_mine_time = 5

        # in memory datastructures.
        self.current_transactions = [] # A list of `Transaction`
        self.chain = [] # A list of `Block`
        self.state = State()

    def is_new_block_valid(self, block, received_blockhash):
        """
        Determine if I should accept a new block.
        Does it pass all semantic checks? Search for "constraint" in this file.

        :param block: A new proposed block
        :return: True if valid, False if not
        """
        # TODO: check if received block is valid DONE
        # 1. Hash should match content
        if block._hash() != received_blockhash:
            return False
        # 2. Previous hash should match previous block
        prev_hash =  self.chain[-1]._hash() if len(self.chain) != 0  else '0xfeedcafe'
        if block.previous_hash != prev_hash:
            return False
        # 3. Transactions should be valid (all apply to block)
        if self.state.validate_txns(block.transactions) != block.transactions:
            return False
        # 4. Block number should be one higher than previous block
        nxt_number = self.chain[-1].number+1 if  len(self.chain) != 0 else 1
        if block.number != nxt_number:
            return False
        # 5. miner should be correct (next RR)
        nxt_miner =  next_miner(self.chain[-1], self.nodes) if len(self.chain) != 0 else min(self.nodes)
        if block.miner != nxt_miner:
            return False

        if block.number == 1:
            self.state.balances['A'] = 10000
            self.state.updates['A'] = [(1, 10000)]
        self.state.apply_block(block)
        return True

    def trigger_new_block_mine(self, genesis=False):
        thread = threading.Thread(target=self.__mine_new_block_in_thread, args=(genesis,))
        thread.start()

    def __mine_new_block_in_thread(self, genesis=False):
        """
        Create a new Block in the Blockchain

        :return: New Block
        """
        logging.info("[MINER] waiting for new transactions before mining new block...")
        time.sleep(self.block_mine_time) # Wait for new transactions to come in
        miner = self.node_identifier
        included_transactions = []

        if genesis:
            included_transactions = []
            block = Block(1, included_transactions, '0xfeedcafe', miner)
        else:
            self.current_transactions.sort()

            # TODO: create a new *valid* block with available transactions. Replace the arguments in the line below. DONE
            block_num = len(self.chain)+1
            included_transactions = self.state.validate_txns(self.current_transactions)
            prev_block_hash = self.chain[-1]._hash()
            block = Block(block_num, included_transactions, prev_block_hash, miner)
             
        # TODO: make changes to in-memory data structures to reflect the new block. Check Blockchain.__init__ method for in-memory datastructures DONE
        self.chain.append(block)
        self.current_transactions = [t for t in self.current_transactions if t not in included_transactions]
        self.state.apply_block(block)
        if genesis:
            self.state.balances['A'] = 10000
            self.state.updates['A'] = [(1, 10000)]

        print(self.state.encode)

        logging.info("[MINER] constructed new block with %d transactions. Informing others about: #%s" % (len(block.transactions), block.hash[:5]))
        # broadcast the new block to all nodes.
        for node in self.nodes:
            if node == self.node_identifier: continue
            print("sending req")
            requests.post(f'http://localhost:{node}/inform/block', json=block.encode())
            

    def new_transaction(self, sender, recipient, amount):
        """ Add this transaction to the transaction mempool. We will try
        to include this transaction in the next block until it succeeds.
        """
        self.current_transactions.append(Transaction(sender, recipient, amount))


# Helper method that returns next miner given a block
def next_miner(block, nodes_list):
    next_miner_idx = (nodes_list.index(block.miner)+1)%len(nodes_list)
    return nodes_list[next_miner_idx]
