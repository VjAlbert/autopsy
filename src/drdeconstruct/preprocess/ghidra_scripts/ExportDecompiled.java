// Esporta in JSON lo pseudocodice C di tutte le funzioni del programma.
// Lanciato da DrDeconstruct tramite analyzeHeadless:
//   -postScript ExportDecompiled.java <output.json> <min_size> <max_functions>
// @category DrDeconstruct

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;

public class ExportDecompiled extends GhidraScript {

    private static String esc(String s) {
        StringBuilder b = new StringBuilder(s.length() + 16);
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        return b.toString();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("Uso: ExportDecompiled.java <output.json> [min_size] [max_functions]");
            return;
        }
        String outPath = args[0];
        long minSize = args.length > 1 ? Long.parseLong(args[1]) : 0;
        int maxFunctions = args.length > 2 ? Integer.parseInt(args[2]) : Integer.MAX_VALUE;

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        String lang = currentProgram.getLanguageID().getIdAsString();
        int exported = 0;
        try (Writer w = new OutputStreamWriter(new FileOutputStream(outPath), StandardCharsets.UTF_8)) {
            w.write("{\"program\":\"" + esc(currentProgram.getName()) + "\",");
            w.write("\"language\":\"" + esc(lang) + "\",\"functions\":[");
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            boolean first = true;
            while (it.hasNext() && exported < maxFunctions && !monitor.isCancelled()) {
                Function f = it.next();
                if (f.isExternal() || f.isThunk()) continue;
                long size = f.getBody().getNumAddresses();
                if (size < minSize) continue;
                DecompileResults res = decomp.decompileFunction(f, 60, monitor);
                if (res == null || !res.decompileCompleted()) continue;
                String code = res.getDecompiledFunction().getC();
                if (!first) w.write(",");
                first = false;
                w.write("{\"name\":\"" + esc(f.getName()) + "\",");
                w.write("\"entry\":\"" + esc(f.getEntryPoint().toString()) + "\",");
                w.write("\"size\":" + size + ",");
                w.write("\"code\":\"" + esc(code) + "\"}");
                exported++;
            }
            w.write("]}");
        } finally {
            decomp.dispose();
        }
        println("DrDeconstruct: esportate " + exported + " funzioni in " + outPath);
    }
}
