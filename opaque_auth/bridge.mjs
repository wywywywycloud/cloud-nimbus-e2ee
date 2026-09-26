// The server uses the exact vendored OPAQUE implementation, without implementing
// any cryptographic primitive here. Protocol data only travels through stdin.
import {randomBytes} from 'node:crypto';
import {pathToFileURL} from 'node:url';

const MAX_BYTES = 32768;
let input = '';
let initialized = false;
try {
  for await (const chunk of process.stdin) {
    input += chunk.toString('utf8');
    if (Buffer.byteLength(input) > MAX_BYTES) throw new Error('input limit');
  }
  const {action, params = {}} = JSON.parse(input);
  const moduleUrl = process.env.OPAQUE_MODULE_PATH
    ? pathToFileURL(process.env.OPAQUE_MODULE_PATH).href
    : new URL('../cloud-cypher/web/vendor/opaque.js', import.meta.url).href;
  const opaque = await import(moduleUrl);
  await opaque.ready;
  initialized = true;
  let result;
  if (action === 'createSetup') {
    result = {serverSetup: opaque.server.createSetup()};
  } else {
    const serverSetup = process.env.OPAQUE_SERVER_SETUP;
    if (!serverSetup) throw new Error('configuration unavailable');
    switch (action) {
      case 'createRegistrationResponse':
        result = opaque.server.createRegistrationResponse({...params, serverSetup});
        break;
      case 'startLogin':
        result = opaque.server.startLogin({...params, serverSetup});
        break;
      case 'finishLogin':
        opaque.server.finishLogin(params);
        // The application only needs authentication, never the session key.
        result = {authenticated: true};
        break;
      case 'validateRegistrationRecord': {
        const {startLoginRequest} = opaque.client.startLogin({password: randomBytes(32).toString('base64url')});
        opaque.server.startLogin({...params, serverSetup, startLoginRequest});
        result = {valid: true};
        break;
      }
      case 'getPublicKey':
        result = {publicKey: opaque.server.getPublicKey(serverSetup)};
        break;
      default:
        throw new Error('unsupported operation');
    }
  }
  const output = JSON.stringify({ok: true, result});
  if (Buffer.byteLength(output) > MAX_BYTES) throw new Error('output limit');
  process.stdout.write(output);
} catch {
  // Do not serialize exceptions: the WASM runtime may include protocol inputs.
  process.stdout.write(JSON.stringify({ok: false, unavailable: !initialized}));
  process.exitCode = 1;
}
