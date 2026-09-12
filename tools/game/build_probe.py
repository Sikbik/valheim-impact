#!/usr/bin/env python3
"""Build the local-only menu validation plugin. Never deploy or launch the game."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.build import discover_runtime


POLICY_TESTS = r'''
using System;
using System.IO;
using System.Collections.Generic;
using ValheimImpact.LocalValidation;
internal static class PolicyTests
{
    static int failures;
    static void Check(bool condition, string name)
    { Console.WriteLine((condition ? "PASS " : "FAIL ") + name); if (!condition) failures++; }
    static bool Reject(Action action)
    { try { action(); return false; } catch (ArgumentException) { return true; } catch (IOException) { return true; } }
    static int Main()
    {
        Check(MenuValidationPolicy.ParseOutput(new[] {"valheim"}) == null, "ordinary launches cannot activate probe");
        Check(MenuValidationPolicy.ParseOutput(new[] {"valheim", "-demomode"}) == null, "demo flag alone cannot activate probe");
        Check(Reject(() => MenuValidationPolicy.ParseOutput(new[] {"valheim", "-vi-menu-validation", "/tmp/probe"})), "probe requires demo flag");
        Check(Reject(() => MenuValidationPolicy.ParseOutput(new[] {"valheim", "-demomode", "-vi-menu-validation", "relative"})), "relative output rejected");
        Check(Reject(() => MenuValidationPolicy.ParseOutput(new[] {"valheim", "-demomode", "-vi-menu-validation"})), "missing output rejected");
        Check(Reject(() => MenuValidationPolicy.ParseOutput(new[] {"valheim", "-demomode", "-vi-menu-validation", "/tmp/a", "-vi-menu-validation", "/tmp/b"})), "duplicate probe flags rejected");
        foreach (string flag in new[] {"-joinserverwithcharacter", "-joincode", "-world", "+connect", "-server"})
            Check(Reject(() => MenuValidationPolicy.ParseOutput(new[] {"valheim", "-demomode", "-vi-menu-validation", "/tmp/probe", flag, "anything"})), "automatic world argument rejected " + flag);
        Check(MenuValidationPolicy.ParseOutput(new[] {"valheim", "-demomode", "-vi-menu-validation", "/tmp/vi-test-output"}) == "/tmp/vi-test-output", "explicit flags select exact output");
        for (int mask = 0; mask < 8; mask++)
        {
            bool menu = (mask & 1) != 0, world = (mask & 2) != 0, player = (mask & 4) != 0;
            Check(MenuValidationPolicy.CanOperate(menu, world, player, "start") == (mask == 1), "menu/world/player guard combination " + mask);
        }
        Check(!MenuValidationPolicy.CanOperate(true, false, false, "main") && !MenuValidationPolicy.CanOperate(true, false, false, ""), "unknown and world scenes cannot authorize actions or quit");
        string root = Path.Combine(Path.GetTempPath(), "vi-probe-policy-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            string game = Path.Combine(root, "game"), saves = Path.Combine(root, "saves"), output = Path.Combine(root, "new-output");
            Directory.CreateDirectory(game); Directory.CreateDirectory(saves);
            Check(MenuValidationPolicy.NewOutput(output, game, saves) == output && !Directory.Exists(output), "output validation itself is read-only");
            Check(Reject(() => MenuValidationPolicy.NewOutput(Path.Combine(game, "probe"), game, saves)), "output cannot enter game tree");
            Check(Reject(() => MenuValidationPolicy.NewOutput(Path.Combine(saves, "probe"), game, saves)), "output cannot enter original save tree");
            Check(Reject(() => MenuValidationPolicy.NewOutput(root, game, saves)), "existing output directory rejected");
            string link = Path.Combine(root, "redirect");
            Directory.CreateSymbolicLink(link, game);
            Check(Reject(() => MenuValidationPolicy.NewOutput(Path.Combine(link, "probe"), game, saves)), "symlink ancestor rejected");
        }
        finally { Directory.Delete(root, true); }
        var slots = new List<int>(8); string limitation; int reads = 0;
        foreach (int length in new[] { 0, 9, 2048 })
            Check(!MenuValidationPairPolicy.TryReadSlots(() => length, values => { reads++; values.Add(11); }, slots, out limitation) && reads == 0 && slots.Count == 0,
                "slot count preflight prevents list read " + length);
        Check(!MenuValidationPairPolicy.TryReadSlots<int>(null, values => reads++, slots, out limitation) && reads == 0,
            "missing scalar capability never invokes list getter");
        Check(MenuValidationPairPolicy.TryReadSlots(() => 2, values => { reads++; values.Add(11); values.Add(22); }, slots, out limitation) &&
            reads == 1 && slots.Count == 2 && slots[1] == 22, "bounded read retains the actual selected secondary slot");
        Check(!MenuValidationPairPolicy.TryReadSlots(() => 2, values => values.Add(11), slots, out limitation) && slots.Count == 0,
            "changed material count invalidates and clears source list");
        Check(MenuValidationPairPolicy.ValidLayout(2, 2, 1) && !MenuValidationPairPolicy.ValidLayout(1, 2, 0) &&
            !MenuValidationPairPolicy.ValidLayout(3, 2, 0) && !MenuValidationPairPolicy.ValidLayout(2, 2, 2),
            "one material per submesh and an existing selected slot are required");
        string identity = MenuValidationPairPolicy.SourceIdentity(70, new[] { 11, 22 }, 1);
        Check(identity == MenuValidationPairPolicy.SourceIdentity(70, new[] { 11, 22 }, 1), "repeated exact source references coalesce");
        Check(identity != MenuValidationPairPolicy.SourceIdentity(70, new[] { 33, 22 }, 1), "different companion material makes source pairing ambiguous");
        Check(identity != MenuValidationPairPolicy.SourceIdentity(70, new[] { 22, 11 }, 1) &&
            identity != MenuValidationPairPolicy.SourceIdentity(71, new[] { 11, 22 }, 1), "source identity retains material order and native mesh identity");
        var borrowed = new[] { new FixtureMaterial(11, false), new FixtureMaterial(22, false) };
        FixtureMaterial[] reference, authored;
        MenuValidationPairPolicy.CreateFixtureSlots(borrowed, 1, (source, index, owned) => new FixtureMaterial(source.Id, owned), out reference, out authored);
        Check(reference.Length == 2 && authored.Length == 2 && ReferenceEquals(reference[0], authored[0]) &&
            !ReferenceEquals(reference[0], borrowed[0]) && !reference[0].Authored && !reference[1].Authored && authored[1].Authored &&
            !ReferenceEquals(reference[1], authored[1]) && !ReferenceEquals(authored[1], borrowed[1]) &&
            reference[0].Id == 11 && reference[1].Id == 22 && authored[1].Id == 22 && !borrowed[1].Authored,
            "secondary-slot fixture owns clones and isolates exactly the selected comparison while preserving all submeshes");
        Check(Reject(() => MenuValidationPairPolicy.CreateFixtureSlots(borrowed, 2,
            (source, index, owned) => { throw new Exception("invalid slot must fail before cloning"); }, out reference, out authored)),
            "invalid selected slot cannot create partial fixture clones");
        Console.WriteLine("Failures: " + failures); return failures == 0 ? 0 : 1;
    }
    private sealed class FixtureMaterial
    {
        internal readonly int Id; internal readonly bool Authored;
        internal FixtureMaterial(int id, bool authored) { Id = id; Authored = authored; }
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'local/build.json')
    parser.add_argument('--test', action='store_true', help='Run pure activation/path/menu guard and selected-material-slot tests without loading Unity or the game')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    dotnet, csc = config['dotnet'], Path(config['roslyn_csc'])
    if not csc.is_file():
        raise ValueError('Configured Roslyn compiler is unavailable')
    output = ROOT / 'build/game-probe'
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'tools/game/MenuValidationProbe.cs'
    command = [dotnet, '--roll-forward', 'Major', str(csc), '-nologo', '-noconfig', '-nostdlib+',
               '-langversion:latest', '-optimize+', '-deterministic+']
    if args.test:
        version, runtime = discover_runtime(dotnet)
        harness = output / 'PolicyTests.cs'
        harness.write_text(POLICY_TESTS)
        target = output / 'PolicyTests.dll'
        refs = sorted(runtime.glob('*.dll'))
        subprocess.run(command + ['-define:PROBE_POLICY_TEST', '-target:exe', '-out:' + str(target)] +
                       ['-reference:' + str(p) for p in refs] + [str(source), str(harness)], check=True)
        target.with_suffix('.runtimeconfig.json').write_text(json.dumps({'runtimeOptions': {
            'tfm': 'net' + '.'.join(version.split('.')[:2]), 'framework': {'name': 'Microsoft.NETCore.App', 'version': version}}}))
        subprocess.run([dotnet, str(target)], check=True)
    else:
        game = Path(config['game_dir'])
        refs = sorted((game / 'valheim_Data/Managed').glob('*.dll'))
        refs.append(game / 'BepInEx/core/BepInEx.dll')
        if not refs or any(not path.is_file() for path in refs):
            raise ValueError('Read-only installed game compile references are missing')
        target = output / 'ValheimImpact.MenuValidation.dll'
        subprocess.run(command + ['-target:library', '-out:' + str(target)] +
                       ['-reference:' + str(p) for p in refs] + [str(source)], check=True)
        print(json.dumps({'output': str(target), 'localOnly': True, 'deployed': False,
                          'launchRequirement': '-demomode -vi-menu-validation /absolute/new/output-directory'}))


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error))
