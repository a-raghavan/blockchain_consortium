from flask import Flask, request, jsonify
import logging
import blockchain as bc
from blockchain import next_miner

# Instantiate the Node
app = Flask(__name__)

# Instantiate the Blockchain
blockchain = bc.Blockchain()

@app.route('/inform/block', methods=['POST'])
def new_block_received():
    values = request.get_json()
    logging.info("Received: " + str(values))

    # Check that the required fields are in the POST'ed data
    required = ['number', 'transactions', 'miner', 'previous_hash', 'hash']
    if not all(k in values for k in required):
        logging.warning("[RPC: inform/block] Missing values")
        return 'Missing values', 400

    block = bc.Block.decode(values)
    valid = blockchain.is_new_block_valid(block, values['hash'])

    if not valid:
        logging.warning("[RPC: inform/block] Invalid block")
        return 'Invalid block', 400

    blockchain.chain.append(block)    # Add the block to the chain
    # Modify any other in-memory data structures to reflect the new block

    # TODO: if I am responsible for next block, start mining it (trigger_new_block_mine). DONE
    if next_miner(block, blockchain.nodes) == blockchain.node_identifier:
        blockchain.trigger_new_block_mine()

    return "OK", 201


@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.get_json()

    # Check that the required fields are in the POST'ed data
    required = ['sender', 'recipient', 'amount']
    if not all(k in values for k in required):
        return 'Missing values', 400

    # Create a new Transaction
    blockchain.new_transaction(values['sender'], values['recipient'], int(values['amount']))
    return "OK", 201


@app.route('/dump', methods=['GET'])
def full_chain():
    response = {
        'chain': [b.encode() for b in blockchain.chain],
        'pending_transactions': [txn.encode() for txn in sorted(blockchain.current_transactions)],
        'state': blockchain.state.encode()
    }
    return jsonify(response), 200

@app.route('/startexp/', methods=['GET'])
def startexp():
    if blockchain.node_identifier == min(blockchain.nodes):
        blockchain.trigger_new_block_mine(genesis=True)
    return 'OK'

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

@app.route('/history', methods=['GET'])
def history():
    account = request.args.get('account', '')
    if account == '':
        return 'Missing values', 400
    data = blockchain.state.history(account)
    return jsonify(data), 200

if __name__ == '__main__':
    from argparse import ArgumentParser
    logging.getLogger().setLevel(logging.INFO)

    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000, type=int, help='port to listen on')
    parser.add_argument('-t', '--blocktime', default=5, type=int, help='Transaction collection time (in seconds) before creating a new block.')
    parser.add_argument('-n', '--nodes', nargs='+', help='ports of all participating nodes (space separated). e.g. -n 5001 5002 5003', required=True)

    args = parser.parse_args()

    # Use port as node identifier.
    port = args.port    
    blockchain.node_identifier = port
    blockchain.block_mine_time = args.blocktime

    for nodeport in args.nodes:
        blockchain.nodes.append(int(nodeport))
    
    blockchain.nodes.sort()

    app.run(host='0.0.0.0', port=port, debug=True)