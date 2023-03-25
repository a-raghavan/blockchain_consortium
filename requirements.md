## Overview
In this assignment, we will expand the implementation of a simple account-based blockchain system.

### A consortium setting
### Background
In class, we have looked at systems that use Nakomoto consensus using Proof of Work. This is one of the primary
consensus mechanisms that exists for pure permissionaless settings (a permissionless setting is one where a node
does not need to know about all other nodes in the system).

In permissioned settings however, one can utilize the knowledge of node membership to come up with 
consensus protocols that are cheaper than proof of work. One such example is Proof of Stake (Ethereum recently switched to this). Similarly, Algorand's leader selection can also be reduced to a sortitioned variant of Proof of Stake (this will become clearer in the Algorand section)

Fundamentally, we want to retain the property that everyone should eventually get a chance to propose a block and have it accepted. This solves problems around censorship, denial of service etc. However, we want to limit the havoc malicious nodes can cause. For e.g. they can continuously propose blocks, forcing honest nodes to do extra wasteful work.
**Fundamentally**, PoS/PoW helps us narrow down which node should be allowed to propose a new block, and solve these problems.

### Why consortium
The above properties are needed in a wild-wild-west malicious setting where no one trusts anyone else. This is indeed the case for decentralized cryptocurrency applications.

However, we need not be always pessimistic. Applications of blockchains exist in semi-trusted settings as well. E.g. consider the 3 banks we have here: UWCU, Chase and BOA(Bank of America). People will want to transfer money using Zelle between accounts that might be on different banks. These banks can run a blockchain amongst themselves where interbank transactions are posted. 

**This is a consortium setting.** Typically, such a setting has the following properties:
 - Everyone is fully aware of the other participating nodes (e.g node-UWCU-1, node-chase-1, node-chase-2, node-BOA-1). Thus, a permissioned setting.
 - There is a reputation associated with each node. If one node acts maliciously, that would lead to bad press for the bank.
 - Nodes act cautiously.
   - They do not have to fight for proposing a block (in contrast to PoW/PoS). This prevents wasted work and therefore leads to extremely high performance.
   - They are still suspicious of the block proposed. (They do not blindly trust the block/transactions received by the other bank and should validate them).
  
(HyperLedger Fabric)[https://www.hyperledger.org/use/fabric] from IBM is a blockchain for a consortium setting. Consortium blockchains can afford to run simple consensus protocols and do not require BFT protocols. Any deviation from the accepted protocol can be used to blacklist nodes.

## Our assignment
The assignment description is fairly straightforward. We give you an incomplete implementation of a simple consortium system. You complete the implementation using all the "# TODO" and "# constraint" comments sprinkled throughout the code. 

Download (TODO requirements.txt) the files (blockchain.py, server.py), and let's get started.

We will play around with a 3-node blockchain, though ideally, it should work for >3 as well. Use tmux, or multiple terminals to run the following commands on 3 different terminals.
```
 > python3 server.py -p 5001 -n 5001 5002 5003
 > python3 server.py -p 5002 -n 5001 5002 5003
 > python3 server.py -p 5003 -n 5001 5002 5003
```

You're going to need a fourth terminal to send commands/instructions to these nodes. E.g. run this to propose a new transaction:
```
 > curl -X POST http://localhost:5001/transactions/new -H 'Content-Type: application/json' -d '{"sender": "A", "recipient": "B", "amount": 10}'
```

You can check the state of a node by running `curl http://localhost:5001/dump`. Change the port number to talk with a different node.

Whenever you make any changes to code, make sure to restart all three instances!

In our consortium setting, we will have nodes propose blocks in a round robin manner. If we have 3 nodes, block 1 *needs* to be proposed by 5001, the second block should be from 5002, third from 5003, the fourth one from 5001 again, and so on.

## Code architecture
### `blockchain.py`
This contains the relevant data structures for storing your blockchain's data, and logic for validations and making the blockchain tick. 

 - `Transaction`: what you might expect. Observe the comments with "# constraint". You don't need to do add anything in these lines, but these are important whenever you want to validate a transaction.
 - `Block`: just read through what all is part of a block, and what constraints they have (again, needed for validation).
 - `State`: you have to implement this class, and most methods in this class. 
   - Reminder, this is an account based blockchain. Thus we would typically be storing key values pairs. e.g. "personA" currently has 500 amount, "personB" has 1000 amount, etc..
   - `validate_txns` is called with a list of transactions. It will try to apply each transaction sequentially. If a transaction cannot be applied, or is invalid, it should not be considered. It will eventually return a list of transactions that can be applied. Consider an example where we call it with `[T1, T2, T3, T4, T5]`. Assume thatT2 is invalid because the sender does not exist in State. T3 is invalid because the sender had insufficient funds. We should return `[T1, T4, T5]`. It should not commit these transactions or apply them to the state.
   - `apply_block`: A new block exists. Change our account info based on this new block.
 - `Blockchain`: The key in-memory datastructures are `current_transactions` which is the list of pending transactions. `chain` is a list of committed blocks, and `state` is your `State`.
   - `is_new_block_valid`: triggered to see if this is a valid block. Remember, it should fulfill *all* constraints.
   - `trigger_new_block_mine`: call this method when you want this node to create a block.
   - `__mine_new_block_in_thread`: this is where you are supposed to create a new *valid* block. A transaction that fails to get in should still be retried during next block. This will also automatically inform its nodes about a new block!

### `server.py`
This defines what a node does when it receives a RPC call (network request).
 - `new_block_received`: Observe that it makes a call to `is_new_block_valid` before accepting it.
   - What all should a node do when it gets a block?

## How you might want to tackle this:
While we will release tests asap, this is an approximate order in which you might want to implement this assignment: 
  - Make nodes propose blocks in a Round Robin fashion. (hint: `server.py::new_block_received`)
  - Work on constructing (`Blockchain.__mine_new_block_in_thread`) a valid block when it's your turn. Change `validate_txns` to always return all the txns. Propose a couple of transactions to different nodes. See if these transactions end up being included in proposed blocks. You can check it by dumping the state (as discussed above, and below in how-to-debug). Or just print stuff to the log.
  - Work on validate_txns: see that invalid txns are not included. 
  - transactions which did not get in should be retried whenever this node tries to mine a new block.

## How to debug.
 - You can send transactions to each node (as shown above the code architecture section)
 - You can get the in-memory state of each node (as discussed above: `curl http://localhost:5001/dump`)
 - In order to actually start the experiment manually, you will need to do this *once* (`curl http://localhost:5001/startexp/`). This forces the first node to create the first (genesis) block and kick-start the rest of the blockchain pipeline.
 - You can control the time a node waits before committing a block to help you propose transactions to a specific node. Just add `-t 10` when you run the command. Each node will wait 10 seconds (or whatever you pass) before it proposes a block.
 - `logging.info("intelligent debugging like Received: " + str(variable) + ' while state was ' + str(somethingelse))`
 - `import pdb; pdb.set_trace()`. Add this line to the code where you want to debug. Then run the code and it 
will stop at that line. You can then inspect the variables and run the code line by line.
 - good ol' `print("bleh")`