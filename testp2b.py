import unittest
import signal
import os, time, random, subprocess, requests

# https://stackoverflow.com/a/49567288
class TestTimeout(Exception):
    pass

class test_timeout:
  def __init__(self, seconds, error_message=None):
    if error_message is None:
      error_message = 'test timed out after {}s.'.format(seconds)
    self.seconds = seconds
    self.error_message = error_message

  def handle_timeout(self, signum, frame):
    raise TestTimeout(self.error_message)

  def __enter__(self):
    signal.signal(signal.SIGALRM, self.handle_timeout)
    signal.alarm(self.seconds)

  def __exit__(self, exc_type, exc_val, exc_tb):
    signal.alarm(0)

def log(msg, level='INFO'):
    print('[%s]: %s' % (level, msg))

server_ports = [5001, 5002, 5003]

BLOCK_COMMIT_TIME=2
POINTS = 0

def stagger():
    time.sleep(BLOCK_COMMIT_TIME/2)

def commit():
    time.sleep(BLOCK_COMMIT_TIME)

class ServerProcess:
    def pid_fname(self):
        return '.pid.server-%d.pid' % self.portnumber

    def __init__(self, portnumber):
        self.portnumber = portnumber
        self.instance = None
        self.base_url = 'http://localhost:%d' % self.portnumber

    def kill_if_running(self):
        fname = self.pid_fname()
        if not os.path.isfile(fname): return
        with open(fname, 'r') as f:
            try:
                pid = int(f.read().strip())
                # log('Killing process with pid: %d' % pid, 'INFO')
                os.kill(pid, 9)
                if self.instance is not None: self.instance.wait()
            except Exception as e:
                log('Unable to read/kill server: %s' % e, 'WARN')
        if os.path.isfile(fname):
            os.remove(fname)

    def restart(self, block_commit_time=4):
        assert(block_commit_time%2 == 0)
        self.kill_if_running()
        if self.instance is not None:
            self.instance.stagger()
            self.instance = None

        time.sleep(0.1)
        if not os.path.exists('./server.py'):
            raise Exception('./server.py not found.')

        for _ in range(3):
            args = [
                'python3', './server.py',
                '-p', str(self.portnumber),
                '-t', str(block_commit_time),
                '-n']
            args.extend([str(x) for x in server_ports])

            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pid = process.pid
            with open(self.pid_fname(), 'w') as f:
                f.write("%d\r\n" % pid)
            time.sleep(0.5)

            if process.poll() is None:
                self.instance = process
                break
        else:
            raise Exception("Unable to start the server. 99% of the time it means that your server crashed as soon as it started. Please check manually. 1% of the time it could be due to overloaded CSL machines, please try again in 10 seconds. This is almost never the case.")

    def check_process_alive(self):
        if self.instance is None: return False
        if self.instance.poll() is not None: return False
        try:
            os.kill(self.instance.pid, 0)
            return True
        except OSError:
            return False

    def ping(self):
        with test_timeout(1):
            r = requests.get(self.base_url + '/health')
            return r.status_code == 200

    def send_txn(self, txn):
        with test_timeout(1):
            r = requests.post(self.base_url + '/transactions/new', json=txn)
            return r.status_code == 201
    
    def send_block(self, block):
        with test_timeout(1):
            r = requests.post(self.base_url + '/inform/block', json=block)
            return r.status_code == 201

    def dump(self):
        with test_timeout(1):
            r = requests.get(self.base_url + '/dump')
            return r.json()

    def genesis(self):
        with test_timeout(1):
            r = requests.get(self.base_url + '/startexp/')
            return r.status_code == 200

    def history(self, account):
        with test_timeout(1):
            r = requests.get(self.base_url + '/history', params={'account': account})
            return r.json()

class TestsUtils():
    @staticmethod
    def txn(sender, recipient, amount):
        return {'sender': sender, 'recipient': recipient, 'amount': amount}

    @staticmethod
    def block(num, txns, prev, miner, hash=None):
        def tx_stringify(t):
            return "T(%s -> %s: %s)" % (t['sender'], t['recipient'], t['amount'])

        import hashlib
        if hash is None: # Generate correct hash
            hash = hashlib.sha256(
                str(num).encode('utf-8') +
                str([tx_stringify(txn) for txn in txns]).encode('utf-8') +
                str(prev).encode('utf-8') +
                str(miner).encode('utf-8')
            ).hexdigest()
        
        return {'number': num, 'transactions': txns, 'previous_hash': prev, 'miner': miner, 'hash': hash}

    @staticmethod
    def checkChainEqualForAll(tst, chain1, chain2, chain3):
        tst.assertTrue(chain1 == chain2 == chain3)

    @staticmethod
    def checkStateEqualForAll(tst, state1, state2, state3):
        tst.assertTrue(state1 == state2 == state3)

    @staticmethod
    def checkBlockBasic(tst, block, expectedBlockNumber, expectedMiner, expectedPrevHash=None):
        tst.assertTrue(block['number'] == expectedBlockNumber)
        if expectedPrevHash is not None:
            tst.assertTrue(block['previous_hash'] == expectedPrevHash)
        expectedMiner = server_ports[(block['number'] - 1) % len(server_ports)]
        tst.assertTrue(block['miner'] == expectedMiner)


class Test1ChainTests(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        for port in server_ports:
            self.nodes.append(ServerProcess(port))
        for node in self.nodes:
            node.restart(BLOCK_COMMIT_TIME)

        self.alive()
    
    def tearDown(self):
        self.alive() # check that all nodes are still alive
        for node in self.nodes:
            node.kill_if_running()
        
    def alive(self):
        for node in self.nodes:
            self.assertTrue(node.check_process_alive())
            self.assertTrue(node.ping())

    def test_a_server_spinsup(self):
        self.alive()
        global POINTS; POINTS += 1

    def test_f_test_genesis_block(self):
        self.assertTrue(self.nodes[0].genesis())
        commit()
        stagger()

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        one = dumps[0]
        self.assertTrue(one['state'] == {'A': 10000})
        self.assertTrue(len(one['chain']) == 1)
        TestsUtils.checkBlockBasic(self, one['chain'][0], 1, server_ports[0], '0xfeedcafe')
        self.assertTrue(len(one.get('transactions', [])) == 0)

        global POINTS; POINTS += 2


    def test_j_block_RR(self):
        self.assertTrue(self.nodes[0].genesis())
        stagger() # This makes us reside in boundary of commits for all future checks.
        lastHash = '0xfeedcafe'
        for blocknumber in range (0, 2*len(self.nodes) + 2):
            if blocknumber == 0: # nothing's committed yet
                for node in self.nodes:
                    self.assertTrue(node.dump().get('chain', []) == [])
                commit()
                continue

            dumps = [node.dump() for node in self.nodes]
            TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps]) # chain is equal for all.
            TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps]) # state is equal for all.
            
            lastBlock = dumps[0]['chain'][-1] # pick any last block. we know all are same because of chain check
            TestsUtils.checkBlockBasic(self, lastBlock, blocknumber, server_ports[blocknumber % len(server_ports)], lastHash)            
            lastHash = lastBlock['hash']
            
            commit()

        global POINTS; POINTS += 10

    
class Test2TxnStateSimple(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        for port in server_ports:
            self.nodes.append(ServerProcess(port))
        for node in self.nodes:
            node.restart(BLOCK_COMMIT_TIME)

        self.alive()
    
    def tearDown(self):
        self.alive() # check that all nodes are still alive
        for node in self.nodes:
            node.kill_if_running()
        
    def alive(self):
        for node in self.nodes:
            self.assertTrue(node.check_process_alive())
            self.assertTrue(node.ping())

    def test_a_basic_txns_are_accepted(self):
        for nodeid, node in enumerate(self.nodes):
            txns = [TestsUtils.txn('s-%d-%d' % (nodeid, i), 'r-%d-%d' % (nodeid, i), i) for i in range(10)]
            for txn in txns: node.send_txn(txn)
            state = node.dump()
            self.assertTrue(len(state.get('chain', [])) == 0)
            self.assertTrue(txns == state.get('pending_transactions', []))
            self.assertTrue(state.get('state', {}) == {})
        
        global POINTS; POINTS += 2


    def test_e_basic_txns_are_committed(self):
        # Start and stagger
        self.nodes[0].genesis()
        stagger()
        last_hash = '0xfeedcafe'

        commit()
        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 5000))
        oneDump = self.nodes[1].dump()
        self.assertTrue(oneDump['pending_transactions'] == [TestsUtils.txn('A', 'B', 5000)])
        TestsUtils.checkBlockBasic(self, oneDump['chain'][0], 1, self.nodes[0], last_hash); last_hash = oneDump['chain'][-1]['hash']

        commit()

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(all(len(d['pending_transactions']) == 0 for d in dumps))
        self.assertTrue(dumps[0]['state'] == {'A': 5000, 'B': 5000})
        TestsUtils.checkBlockBasic(self, dumps[0]['chain'][1], 2, self.nodes[1], last_hash); last_hash = dumps[0]['chain'][-1]['hash']

        self.nodes[2].send_txn(TestsUtils.txn('B', 'C', 1000))
        self.nodes[2].send_txn(TestsUtils.txn('B', 'A', 1000))
        commit()

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(all(len(d['pending_transactions']) == 0 for d in dumps))
        self.assertTrue(dumps[0]['state'] == {'A': 6000, 'B': 3000, 'C': 1000})
        TestsUtils.checkBlockBasic(self, dumps[0]['chain'][2], 3, self.nodes[2], last_hash); last_hash = dumps[0]['chain'][-1]['hash']

        global POINTS; POINTS += 5


    def test_f_txns_are_aborted(self):
        self.nodes[0].genesis()
        stagger()

        commit()
        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 5000))
        commit()

        # Should fail because A does not have enough money left
        self.nodes[2].send_txn(TestsUtils.txn('A', 'B', 5200))
        commit()
        
        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[2]['pending_transactions'] == [TestsUtils.txn('A', 'B', 5200)])
        self.assertTrue(dumps[2]['state'] == {'A': 5000, 'B': 5000})

        self.nodes[0].send_txn(TestsUtils.txn('C', 'A', 1))
        commit()

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[0]['pending_transactions'] == [TestsUtils.txn('C', 'A', 1)])
        self.assertTrue(dumps[0]['state'] == {'A': 5000, 'B': 5000})

        global POINTS; POINTS += 5


    def test_o_txns_are_retried(self):
        self.nodes[0].genesis()
        stagger()
        commit() # 0 committed
        
        self.nodes[1].send_txn(TestsUtils.txn('B', 'C', 1000))
        commit() # 1 committed 
        commit() # 2 committed 

        self.nodes[0].send_txn(TestsUtils.txn('C', 'A', 1000))
        commit() # 0 committed
        commit() # 1 committed

        self.nodes[2].send_txn(TestsUtils.txn('A', 'B', 5000))
        commit() # 2 committed

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[2]['pending_transactions'] == [])
        self.assertTrue(dumps[2]['state'] == {'A': 5000, 'B': 5000})
        self.assertTrue(dumps[2]['chain'][-1]['transactions'] == [TestsUtils.txn('A', 'B', 5000)])

        commit() # 0 committed
        commit() # 1 committed

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[1]['pending_transactions'] == [])
        self.assertTrue(dumps[1]['state'] == {'A': 5000, 'B': 4000, 'C': 1000})
        self.assertTrue(dumps[1]['chain'][-1]['transactions'] == [TestsUtils.txn('B', 'C', 1000)])

        commit() # 2 committed
        commit() # 0 committed

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[0]['pending_transactions'] == [])
        self.assertTrue(dumps[0]['state'] == {'A': 6000, 'B': 4000, 'C': 0})
        self.assertTrue(dumps[0]['chain'][-1]['transactions'] == [TestsUtils.txn('C', 'A', 1000)])

        global POINTS; POINTS += 6


    def test_u_invalid_txns_are_filtered(self):
        self.nodes[0].genesis()
        stagger()
        commit()

        self.nodes[1].send_txn(TestsUtils.txn('C', 'D', 201))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 2000))
        self.nodes[1].send_txn(TestsUtils.txn('D', 'E', 21))
        commit()

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[1]['pending_transactions'] == [TestsUtils.txn('C', 'D', 201), TestsUtils.txn('D', 'E', 21)])
        self.assertTrue(dumps[0]['state'] == {'A': 8000, 'B': 2000})
        self.assertTrue(dumps[0]['chain'][-1]['transactions'] == [TestsUtils.txn('A', 'B', 2000)])

        global POINTS; POINTS += 3


class Tests3UpdateableState(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        for port in server_ports:
            self.nodes.append(ServerProcess(port))
        for node in self.nodes:
            node.restart(BLOCK_COMMIT_TIME)

        self.alive()
    
    def tearDown(self):
        self.alive() # check that all nodes are still alive
        for node in self.nodes:
            node.kill_if_running()
        
    def alive(self):
        for node in self.nodes:
            self.assertTrue(node.check_process_alive())
            self.assertTrue(node.ping())

    def test_a_simple_state_updates(self):
        self.nodes[0].genesis()
        stagger()
        commit()

        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 2500))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 3000))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'C', 550))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'C', 2800))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 1000))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'C', 550))

        commit()
        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[1]['pending_transactions'] == [TestsUtils.txn('A', 'C', 2800)])
        self.assertTrue(dumps[1]['state'] == {'A': 2400, 'B': 6500, 'C': 1100})
        self.assertTrue(dumps[1]['chain'][-1]['transactions'] == [TestsUtils.txn('A', 'B', 1000), TestsUtils.txn('A', 'B', 2500), TestsUtils.txn('A', 'B', 3000), TestsUtils.txn('A', 'C', 550), TestsUtils.txn('A', 'C', 550)])

        global POINTS; POINTS += 5


    def test_e_check_transitive_validity_changes(self):
        self.nodes[0].genesis()
        stagger()
        commit()

        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 4000))
        self.nodes[1].send_txn(TestsUtils.txn('B', 'C', 1000))
        self.nodes[1].send_txn(TestsUtils.txn('C', 'A', 500))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'D', 6500))

        commit()
        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[1]['pending_transactions'] == [TestsUtils.txn('A', 'D', 6500)])
        self.assertTrue(dumps[1]['state'] == {'A': 6500, 'B': 3000, 'C': 500})
        self.assertTrue(dumps[1]['chain'][-1]['transactions'] == [TestsUtils.txn('A', 'B', 4000), TestsUtils.txn('B', 'C', 1000), TestsUtils.txn('C', 'A', 500)])
        # We don't expect you to make multiple passes to check which all transactions go in. That becomes an algorithmically hard problem.
        # Systemsy way to solve this is pick an ordering, validate txns based on ordering. And then retry during next block mining. Eventually, txn will commit
        # Also, in real world systems, such a transaction is available with multiple nodes all of whom will be trying to include it in their block.

        commit() # 2
        commit() # 0
        commit() # 1

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[1]['pending_transactions'] == [])
        self.assertTrue(dumps[1]['state'] == {'A': 0, 'B': 3000, 'C': 500, 'D': 6500})
        self.assertTrue(dumps[1]['chain'][-1]['transactions'] == [TestsUtils.txn('A', 'D', 6500)])

        global POINTS; POINTS += 7



    def test_i_check_eventual_validity(self):
        self.nodes[0].genesis()
        stagger()
        commit()

        self.nodes[1].send_txn(TestsUtils.txn('C', 'A', 1500))
        self.nodes[1].send_txn(TestsUtils.txn('B', 'C', 2000))
        self.nodes[2].send_txn(TestsUtils.txn('A', 'B', 2500))

        commit() #1 // empty 
        commit() #2 // will have A->B 2500
        commit() #0 // empty
        commit() #1 // should trigger interesting stuff.

        dumps = [n.dump() for n in self.nodes]
        TestsUtils.checkChainEqualForAll(self, *[d['chain'] for d in dumps])
        TestsUtils.checkStateEqualForAll(self, *[d['state'] for d in dumps])
        self.assertTrue(dumps[1]['pending_transactions'] == [])
        self.assertTrue(dumps[1]['state'] == {'A': 9000, 'B': 500, 'C': 500})
        self.assertTrue(dumps[1]['chain'][-1]['transactions'] == [TestsUtils.txn('B', 'C', 2000), TestsUtils.txn('C', 'A', 1500)])

        global POINTS; POINTS += 6


class Tests4SemanticValidations(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        for port in server_ports:
            self.nodes.append(ServerProcess(port))
        for node in self.nodes:
            node.restart(BLOCK_COMMIT_TIME)

        self.alive()
    
    def tearDown(self):
        self.alive() # check that all nodes are still alive
        for node in self.nodes:
            node.kill_if_running()
        
    def alive(self):
        for node in self.nodes:
            self.assertTrue(node.check_process_alive())
            self.assertTrue(node.ping())

    def test_a_txn_invalid_drop(self):
        self.assertFalse(self.nodes[0].send_txn({}))
        self.assertFalse(self.nodes[0].send_txn({'sender': 'A'}))
        self.assertFalse(self.nodes[0].send_txn({'sender': 'A', 'recipient': 'B'}))

        global POINTS; POINTS += 1


    def test_e_correct_blocks(self):
        prev = '0xfeedcafe'
        block = TestsUtils.block(1, [], prev, server_ports[0]); prev = block['hash']
        for node in self.nodes:
            self.assertTrue(node.send_block(block))

        txns = [TestsUtils.txn('A', 'B', 2500)]
        block = TestsUtils.block(2, txns, prev, server_ports[1]); prev = block['hash']
        for node in self.nodes:
            self.assertTrue(node.send_block(block))

        global POINTS; POINTS += 1


    def test_f_incorrect_blocks_prev_hash(self):
        # incorrect previous hash - genesis
        prev = '0xincorrect'
        block = TestsUtils.block(1, [], prev, server_ports[0]); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))

        # incorrect previous hash - normal
        prev = '0xfeedcafe'
        block = TestsUtils.block(1, [], prev, server_ports[0]); prev = block['hash']
        self.assertTrue(self.nodes[2].send_block(block))
        block = TestsUtils.block(2, [], prev, server_ports[1], '0xtamperedHash'); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))

        global POINTS; POINTS += 2


    def test_g_incorrect_blocks_miner(self):
        # Incorrect miner -- genesis
        prev = '0xfeedcafe'
        block = TestsUtils.block(1, [], prev, server_ports[1]); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))

        # incorrect miner - normal
        prev = '0xfeedcafe'
        block = TestsUtils.block(1, [], prev, server_ports[0]); prev = block['hash']
        self.assertTrue(self.nodes[2].send_block(block))
        block = TestsUtils.block(2, [], prev, server_ports[2]); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))

        global POINTS; POINTS += 2


    def test_h_incorrect_block_number(self):
        # Incorrect block number -- genesis
        prev = '0xfeedcafe'
        block = TestsUtils.block(2, [], prev, server_ports[0]); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))

        # Incorrect block number -- normal
        prev = '0xfeedcafe'
        block = TestsUtils.block(1, [], prev, server_ports[0]); prev = block['hash']
        self.assertTrue(self.nodes[2].send_block(block))
        block = TestsUtils.block(1, [], prev, server_ports[1]); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))
        block = TestsUtils.block(3, [], prev, server_ports[1]); prev = block['hash']
        self.assertFalse(self.nodes[2].send_block(block))

        global POINTS; POINTS += 2


    def test_i_sus_miner(self):
        prev = '0xfeedcafe'
        block = TestsUtils.block(1, [], prev, 1337); prev = block['hash'] # random person is trying to commit a block.
        self.assertFalse(self.nodes[2].send_block(block))

        global POINTS; POINTS += 1


    def test_j_invalid_txns_in_block(self):
        self.nodes[0].genesis()
        stagger()
        commit()
        # Now A->10000

        prev = self.nodes[0].dump()['chain'][-1]['hash']
        block = TestsUtils.block(2, [TestsUtils.txn('A', 'B', 20000)], prev, server_ports[1]);
        self.assertFalse(self.nodes[0].send_block(block))

        block = TestsUtils.block(2, [TestsUtils.txn('C', 'A', 200)], prev, server_ports[1]);
        self.assertFalse(self.nodes[0].send_block(block))

        block = TestsUtils.block(2, [TestsUtils.txn('A', 'B', 6000), TestsUtils.txn('A', 'C', 6000)], prev, server_ports[1])
        self.assertFalse(self.nodes[0].send_block(block))

        block = TestsUtils.block(2, [TestsUtils.txn('A', 'B', 6000), TestsUtils.txn('B', 'C', 3000)], prev, server_ports[1])
        self.assertTrue(self.nodes[0].send_block(block))
        state = self.nodes[0].dump()['state']
        self.assertTrue(state == {'A': 4000, 'B': 3000, 'C': 3000})

        global POINTS; POINTS += 4


class Tests5History(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        for port in server_ports:
            self.nodes.append(ServerProcess(port))
        for node in self.nodes:
            node.restart(BLOCK_COMMIT_TIME)
        self.alive()
    
    def tearDown(self):
        self.alive()
        for node in self.nodes:
            node.kill_if_running()
        
    def alive(self):
        for node in self.nodes:
            self.assertTrue(node.check_process_alive())
            self.assertTrue(node.ping())

    def test_a_history_genesis(self):
        self.nodes[0].genesis()
        stagger()
        commit()

        self.assertTrue(self.nodes[0].history('A') == [[1, 10000]])
        global POINTS; POINTS += 1
    
    def test_b_history_missing(self):
        self.assertTrue(self.nodes[0].history('404') == [])
        global POINTS; POINTS += 1

    def test_c_history_simple(self):
        self.nodes[0].genesis()
        stagger()
        commit() # 0

        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 5000))
        self.nodes[2].send_txn(TestsUtils.txn('B', 'C', 1500))
        self.nodes[0].send_txn(TestsUtils.txn('C', 'A', 100))

        commit() # 1
        commit() # 2
        commit() # 0

        historiesA = [node.history('A') for node in self.nodes]
        historiesB = [node.history('B') for node in self.nodes]
        historiesC = [node.history('C') for node in self.nodes]

        # Everyone returned the same thing at least.
        self.assertTrue(all(h == historiesA[0] for h in historiesA))
        self.assertTrue(all(h == historiesB[0] for h in historiesB))
        self.assertTrue(all(h == historiesC[0] for h in historiesC))

        self.assertTrue(historiesA[0] == [[1, 10000], [2, -5000], [4, 100]])
        self.assertTrue(historiesB[0] == [[2, 5000], [3, -1500]])
        self.assertTrue(historiesC[0] == [[3, 1500], [4, -100]])

        global POINTS; POINTS += 3


    def test_e_history_aggregated_in_blocks(self):
        self.nodes[0].genesis()
        stagger()
        commit() # 0


        self.nodes[1].send_txn(TestsUtils.txn('A', 'B', 500))
        self.nodes[1].send_txn(TestsUtils.txn('A', 'D', 100000))
        self.nodes[2].send_txn(TestsUtils.txn('A', 'B', 1500))
        self.nodes[2].send_txn(TestsUtils.txn('B', 'C', 100))
        self.nodes[2].send_txn(TestsUtils.txn('B', 'A', 100))

        commit() # 1
        commit() # 2

        historiesA = [node.history('A') for node in self.nodes]
        historiesB = [node.history('B') for node in self.nodes]
        historiesC = [node.history('C') for node in self.nodes]

        # Everyone returned the same thing at least.
        self.assertTrue(all(h == historiesA[0] for h in historiesA))
        self.assertTrue(all(h == historiesB[0] for h in historiesB))
        self.assertTrue(all(h == historiesC[0] for h in historiesC))

        self.assertTrue(historiesA[0] == [[1, 10000], [2, -500], [3, -1400]])
        self.assertTrue(historiesB[0] == [[2, 500], [3, 1300]])
        self.assertTrue(historiesC[0] == [[3, 100]])

        global POINTS; POINTS += 10


if __name__ == '__main__':
    unittest.main(exit=False)
    print("Points: %s" % POINTS)